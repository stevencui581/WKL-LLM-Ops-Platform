"""指标公式测试（方案 TASK-10 / 6.2.1）—— 断言值取自 253 实测。"""

from __future__ import annotations

import pytest

from app.collectors.gpu import parse_compute_apps, parse_gpu_csv, parse_pmon
from app.collectors.prometheus import PrometheusCollector, parse_prometheus
from app.collectors.props import parse_models, parse_props
from app.collectors.slots import build_kv_block, parse_slots, slot_state
from app.services.kvmode import KvCapacity


def _cap(total: int, mode: str = "unified", source: str = "unit_kv_flag") -> KvCapacity:
    """构造 KV 容量（v0.4 §5.3：build_kv_block 接收判定结果，不再收裸整数）。"""
    return KvCapacity(total_tokens=total, mode=mode, source=source)


METRICS_TEXT = """# HELP llamacpp:requests_processing
# TYPE llamacpp:requests_processing gauge
llamacpp:requests_processing 1
llamacpp:requests_deferred 0
llamacpp:tokens_predicted_total 1198564
llamacpp:tokens_predicted_seconds_total 17600
llamacpp:prompt_tokens_total 42000
llamacpp:prompt_seconds_total 750
llamacpp:prompt_tokens_cached_total 18000
llamacpp:spec_decode_num_drafts_total 200
llamacpp:spec_decode_num_draft_tokens_total 516
llamacpp:spec_decode_num_accepted_tokens_total 422
some_other_metric 42
"""


class TestSlotsFormulas:
    def test_parse_real_payload(self, slots_payload):
        slots = parse_slots(slots_payload)
        assert len(slots) == 6
        assert [s.id for s in slots] == [0, 1, 2, 3, 4, 5]
        assert all(s.n_ctx == 131072 for s in slots)
        assert slots[2].n_prompt_tokens == 56414
        assert slots[2].speculative_types == "none,draft-mtp"

    def test_kv_pool_is_sum_not_max(self, slots_payload):
        """-kvu 统一池：必须求和，不能取单槽最大值。"""
        slots = parse_slots(slots_payload)
        kv = build_kv_block(slots, _cap(131072))
        assert kv.used_tokens == 56414
        assert abs(kv.pct - 43.04) < 0.01
        assert kv.remaining_tokens == 131072 - 56414 == 74658
        # 若误用「单槽最大值」算法，占用率会是 43.04% 而非 0%；两者都能过，
        # 因此再用一个多槽同时占用的构造来区分
        slots2 = parse_slots(
            [
                {
                    "id": 0,
                    "n_ctx": 131072,
                    "n_prompt_tokens": 1000,
                    "next_token": [{"n_decoded": 0}],
                    "params": {},
                },
                {
                    "id": 1,
                    "n_ctx": 131072,
                    "n_prompt_tokens": 2000,
                    "next_token": [{"n_decoded": 0}],
                    "params": {},
                },
            ]
        )
        kv2 = build_kv_block(slots2, _cap(131072))
        assert kv2.used_tokens == 3000  # 求和 = 3000
        assert kv2.used_tokens != 2000  # 不是最大值
        assert abs(kv2.pct - 3000 / 131072 * 100) < 1e-9

    def test_slot_state_three_way(self):
        assert slot_state(True, 0) == "generating"
        assert slot_state(True, 999) == "generating"
        assert slot_state(False, 56414) == "cached"
        assert slot_state(False, 0) == "idle"

    def test_real_states(self, slots_payload):
        slots = parse_slots(slots_payload)
        assert slots[2].state == "cached"
        assert all(s.state == "idle" for s in slots if s.id != 2)

    def test_zero_total_ctx_no_division_error(self, slots_payload):
        kv = build_kv_block(parse_slots(slots_payload), _cap(0))
        assert kv.pct is None
        assert kv.remaining_tokens == 0

    def test_malformed_entries_ignored(self):
        slots = parse_slots([{"id": 0, "n_ctx": 1024, "n_prompt_tokens": 5}, "junk", None])
        assert len(slots) == 1
        assert slots[0].n_prompt_tokens == 5

    def test_source_is_none_not_fake(self, slots_payload):
        """/slots 不返回客户端 IP —— 取不到时必须为 None，不得伪造。"""
        slots = parse_slots(slots_payload)
        assert all(s.source is None for s in slots)


class TestPropsFormulas:
    def test_parse_props(self, props_payload):
        p = parse_props(props_payload)
        assert p["total_slots"] == 6
        assert p["n_ctx"] == 131072
        assert p["model_ftype"] == "Q4_K - Medium"
        assert p["endpoint_metrics"] is False
        assert p["endpoint_slots"] is True
        assert p["ui"] is True

    def test_parse_models(self, models_payload):
        m = parse_models(models_payload)
        assert m.n_params == 27320697856
        assert m.n_ctx_train == 262144
        assert m.n_ctx == 131072
        assert m.ftype == "Q4_K - Medium"
        assert m.name.endswith(".gguf")

    def test_runtime_config_badges(self, settings, props_payload, models_payload):
        from app.collectors.props import PropsCollector

        class FakeClient:
            async def props(self_inner):
                return True, props_payload, None

            async def models(self_inner):
                return True, models_payload, None

        c = PropsCollector(settings, FakeClient())
        import asyncio

        from app.services.unitinfo import UnitConfig, parse_unit_text

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c.collect(force=True))

        unit = UnitConfig(
            spec_type="draft-mtp",
            draft_n_max=2,
            tensor_split="1,1",
            n_ctx=131072,
            parallel=6,
            flash_attn=True,
        )

        # 全部来源都只给默认值 "none" 时，徽标如实显示“关闭”，不编造
        rt_default = c.runtime_config(gpu_count=2, unit=UnitConfig(), slot_spec_types="")
        assert "draft-mtp" not in " ".join(rt_default.badges)

        # unit 是权威来源：/props 说 none、unit 说 draft-mtp → 显示 draft-mtp
        rt = c.runtime_config(gpu_count=2, unit=unit, slot_spec_types="")
        assert rt.spec_types == "draft-mtp"
        assert rt.model_ftype == "Q4_K - Medium"
        assert rt.metrics_enabled is False
        blob = " ".join(rt.badges)
        assert "128K" in blob
        assert "draft-mtp" in blob
        assert "draft 2(+1)" in blob
        assert "tensor-split 1,1" in blob

        # /slots 有更具体的值（含 none,draft-mtp）时优先于 unit
        rt2 = c.runtime_config(gpu_count=2, unit=unit, slot_spec_types="none,draft-mtp")
        assert rt2.spec_types == "none,draft-mtp"

        # 真正解析一份 unit 文本
        parsed = parse_unit_text(
            "[Service]\nExecStart=/x/llama-server -ts 1,1 -c 131072 --parallel 6 "
            "-fa on --spec-type draft-mtp --spec-draft-n-max 2\n"
        )
        rt3 = c.runtime_config(gpu_count=2, unit=parsed, slot_spec_types="")
        assert rt3.spec_types == "draft-mtp"
        assert rt3.draft_n_max == 2
        assert rt3.tensor_split == "1,1"

    def test_aggregator_prefers_slot_spec_types(self, settings, slots_payload, props_payload, models_payload):
        """/props 说 none、/slots 说 none,draft-mtp 时，徽标必须显示后者。"""
        from app.collectors.props import PropsCollector
        from app.collectors.slots import SlotsCollector

        class FakeClient:
            async def props(self_inner):
                return True, props_payload, None

            async def models(self_inner):
                return True, models_payload, None

            async def slots(self_inner):
                return True, slots_payload, None

        fc = FakeClient()
        props = PropsCollector(settings, fc)
        slots = SlotsCollector(settings, fc)

        import asyncio

        async def go():
            await props.collect(force=True)
            await slots.collect()

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go())
        rt = props.runtime_config(2, None, slots.slots[0].speculative_types)
        assert rt.spec_types == "none,draft-mtp"


class TestGpuFormulas:
    def test_parse_real_csv(self, nvidia_csv):
        gpus = parse_gpu_csv(nvidia_csv)
        assert len(gpus) == 2
        g0 = gpus[0]
        assert g0.temp_c == 31
        assert g0.power_w == 39.55
        assert g0.mem_used_mib == 14593
        assert g0.mem_total_mib == 16384
        assert g0.clk_sm_mhz == 1312
        assert g0.clk_mem_mhz == 877
        assert g0.pcie_gen == 3
        assert g0.pcie_width == 16

    def test_fan_queried_and_na_is_none(self, nvidia_csv):
        """v0.4 F3：必须**查询** fan.speed；SXM2 返回 [N/A] → None（不显示）。

        v0.1 的做法是把 fan_pct 恒置 None 并不查询，导致 PCIe 卡有风扇也不显示。
        """
        from app.collectors.gpu import QUERY_FIELDS, query_argv

        assert "fan.speed" in QUERY_FIELDS, "必须实际查询 fan.speed"
        assert any("fan.speed" in a for a in query_argv("nvidia-smi"))
        # 目标 的 SXM2 无风扇 → [N/A] → None
        assert all(g.fan_pct is None for g in parse_gpu_csv(nvidia_csv))
        # 有风扇的卡（数值）必须被保留
        line = nvidia_csv.splitlines()[0].rsplit(",", 1)[0] + ", 47"
        assert parse_gpu_csv(line)[0].fan_pct == 47

    def test_na_becomes_none_not_zero(self):
        """[N/A] 必须转 None，转成 0 会产生假的低功耗告警。"""
        csv_line = (
            "0, Tesla V100, uuid-x, 0000:01:00.0, [N/A], [N/A], [N/A], "
            "16384, 14593, 1552, [N/A], [N/A], [N/A], 877, 3, 16, [N/A]"
        )
        g = parse_gpu_csv(csv_line)[0]
        assert g.temp_c is None
        assert g.power_w is None
        assert g.util_gpu_pct is None
        assert g.fan_pct is None
        assert g.temp_c != 0

    def test_row_without_fan_column_still_parsed(self):
        """兼容旧版 nvidia-smi（不返回 fan.speed）：整行不应被丢弃。"""
        old_line = (
            "0, Tesla V100-SXM2-16GB, uuid-x, 0000:01:00.0, 31, 39.55, 300.00, "
            "16384, 14593, 1552, 0, 0, 1312, 877, 3, 16"
        )
        gpus = parse_gpu_csv(old_line)
        assert len(gpus) == 1
        assert gpus[0].temp_c == 31
        assert gpus[0].fan_pct is None

    def test_bandwidth_approx(self, nvidia_csv):
        gpus = parse_gpu_csv(nvidia_csv)
        assert all(g.bandwidth_gbps == 0.0 for g in gpus)  # util.memory = 0
        # 把 util.gpu(:0) 与 util.memory(:0) 改成 50 / 40
        line = nvidia_csv.splitlines()[0].replace(", 0, 0, 1312", ", 50, 40, 1312")
        g = parse_gpu_csv(line)[0]
        # v0.4 F2：峰值带宽按**型号查规格表**，不再用写死的 900
        from app.services import gpu_spec

        peak = gpu_spec.bandwidth_of(g.name)
        assert peak is not None, "V100 应在规格表中"
        assert g.bandwidth_gbps == pytest.approx(peak * 0.40, abs=0.1)

    def test_unknown_model_bandwidth_is_none(self, nvidia_csv):
        """未收录型号 → 带宽 None，绝不套用其它卡的值（v0.4 F2）。"""
        line = (
            nvidia_csv.splitlines()[0]
            .replace("Tesla V100-SXM2-16GB", "Mystery Accelerator 9000")
            .replace(", 0, 0, 1312", ", 50, 40, 1312")
        )
        g = parse_gpu_csv(line)[0]
        assert g.bandwidth_gbps is None
        assert g.mem_type == ""

    def test_fan_value_from_pcie_card_is_kept(self, nvidia_csv):
        """v0.4 F3：有风扇的卡（PCIe）必须显示转速，不能被恒置 None。"""
        line = nvidia_csv.splitlines()[0]
        # 把末列的 [N/A] 换成真实转速
        with_fan = line.rsplit(",", 1)[0] + ", 47"
        assert parse_gpu_csv(with_fan)[0].fan_pct == 47

    def test_compute_apps_and_pmon(self):
        apps = parse_compute_apps(
            "1261, /home/llmops/llama.cpp/build-v050/bin/llama-server, 14590 MiB, GPU-449baa41"
        )
        assert apps["GPU-449baa41"][0].pid == 1261
        assert apps["GPU-449baa41"][0].mem_mib == 14590  # 「14590 MiB」需能解析
        assert apps["GPU-449baa41"][0].name == "llama-server"
        pmon = parse_pmon("# gpu pid type sm mem\n    0       1261     C     17      0      -      -\n")
        assert pmon[0][1261] == 17.0


class TestPrometheusFormulas:
    def test_parse_only_wanted_series(self):
        v = parse_prometheus(METRICS_TEXT)
        assert "llamacpp:tokens_predicted_total" in v
        assert "some_other_metric" not in v
        assert v["llamacpp:requests_deferred"] == 0

    def test_derived_quantities(self, settings):
        c = PrometheusCollector(settings, client=None)
        c.values = parse_prometheus(METRICS_TEXT)
        c.available = True
        assert c.tokens_predicted_total() == 1198564
        assert c.requests_deferred() == 0
        # 解码速率必须由计数器推导，不能用 predicted_tokens_seconds（空闲时为 0）
        assert c.decode_tps() == pytest.approx(1198564 / 17600, rel=1e-6)
        # MTP 接受率 = accepted / draft_tokens
        assert c.mtp_accept() == pytest.approx(422 / 516, rel=1e-6)
        # 缓存命中率 = cached / (cached + prefill)
        assert c.cache_hit_ratio() == pytest.approx(18000 / (18000 + 42000), rel=1e-6)

    def test_no_division_on_zero(self, settings):
        c = PrometheusCollector(settings, client=None)
        c.values = {"llamacpp:tokens_predicted_total": 10.0, "llamacpp:tokens_predicted_seconds_total": 0.0}
        assert c.decode_tps() is None
        c.values = {"llamacpp:prompt_tokens_cached_total": 0.0, "llamacpp:prompt_tokens_total": 0.0}
        assert c.cache_hit_ratio() is None


class TestMtpAcceptance:
    def test_reported_baseline_is_learned_not_hardcoded(self, tmp_path):
        """v0.4 F4：253 实测 422/516 = 81.78% 不再写进配置，改由自动学习得到。

        本用例验证：同样的样本喂给基线学习器后，能得到与实测一致的基线。
        """
        from app.config import Settings
        from app.services.baseline import BaselineLearner

        s = Settings(
            state_dir=str(tmp_path / "s"),
            baseline_persist_path=str(tmp_path / "b.json"),
            baseline_warmup_s=0,
            baseline_min_samples=3,
        )
        # 配置里不得有写死的数值
        assert s.mtp_accept_baseline is None
        assert s.decode_baseline_tps is None

        bl = BaselineLearner(s)
        for _ in range(3):
            bl.observe(422 / 516, 68.22)
        # 基线保留 4 位小数（足够判定用，避免无意义的浮点噪声）
        assert bl.mtp_baseline == pytest.approx(422 / 516, abs=1e-4)
        assert bl.decode_baseline == pytest.approx(68.22, abs=0.001)
