"""多框架 Prometheus 指标守卫（v0.6.1 回归）。

**修的两个真实缺陷**

  1. **D1：指标采集被 /props 开关覆盖。**
     ``aggregator._collect_all()`` 原先无条件执行
     ``metrics.set_endpoint_enabled(self.props.metrics_enabled)``，
     把 ``set_framework()`` 里按 ``CAP_METRICS`` 做的判断覆盖掉。
     vLLM / SGLang 没有 ``/props``，该值恒为 ``False`` ——
     于是即便框架声明了 ``CAP_METRICS``，``/metrics`` 也**永远不会被采集**。

  2. **D2：指标名写死成 llamacpp:。**
     ``prometheus.py`` 里 ``WANTED = ("llamacpp:...",)``，
     即使真的去采集，vLLM 的 ``vllm:*`` / SGLang 的 ``sglang:*`` 也会被
     全部过滤掉 —— 表现为"接口有数据，界面却显示指标不可用"。

本文件同时守住修复后的结构：指标名映射必须留在 ``SPECS`` 数据表里，
采集器只认"概念"，新增框架不需要改采集器代码。
"""

from __future__ import annotations

import asyncio

import pytest

from app.collectors.prometheus import PrometheusCollector, parse_prometheus
from app.config import Settings
from app.services import framework as fw

# ---------------------------------------------------------------- 假响应
VLLM_TABLE = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "meta-llama/Llama-3-8B"}]}, None),
    "/version": (True, "0.6.3.post1", None),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (False, None, "HTTP 404"),
}

SGLANG_TABLE = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "qwen2.5-7b"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (True, {"model_path": "/models/qwen2.5-7b"}, None),
    "/get_server_info": (True, {"version": "0.4.6"}, None),
}

OLLAMA_TABLE = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "llama3.2"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (True, {"version": "0.5.4"}, None),
    "/api/tags": (True, {"models": []}, None),
    "/get_model_info": (False, None, "HTTP 404"),
}

LLAMA_TABLE = {
    "/props": (
        True,
        {
            "build_info": "b11146-7fe450e19",
            "total_slots": 6,
            "default_generation_settings": {"n_ctx": 131072},
            "endpoint_metrics": True,
        },
        None,
    ),
    "/slots": (True, [{"id": 0, "n_ctx": 131072}], None),
    "/health": (True, {"status": "ok"}, None),
    "/v1/models": (True, {"models": [{"name": "qwen3"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (False, None, "HTTP 404"),
}

# ---------------------------------------------------------------- 假指标文本
VLLM_TEXT = """\
# HELP vllm:num_requests_running Number of requests running
vllm:num_requests_running 3
vllm:num_requests_waiting 7
vllm:prompt_tokens_total 12000
vllm:generation_tokens_total 34000
vllm:spec_decode_num_draft_tokens_total 1000
vllm:spec_decode_num_accepted_tokens_total 820
vllm:request_success_total 42
unrelated_metric 1
"""

SGLANG_TEXT = """\
sglang:num_running_reqs 2
sglang:num_queue_reqs 5
sglang:prompt_tokens_total 900
sglang:generation_tokens_total 2100
some_other_metric 99
"""

LLAMA_TEXT = """\
llamacpp:requests_processing 1
llamacpp:requests_deferred 0
llamacpp:tokens_predicted_total 1198564
llamacpp:tokens_predicted_seconds_total 17600
llamacpp:prompt_tokens_total 42000
llamacpp:prompt_tokens_cached_total 18000
llamacpp:spec_decode_num_draft_tokens_total 516
llamacpp:spec_decode_num_accepted_tokens_total 422
"""


def _detect(table: dict) -> fw.FrameworkInfo:
    async def fetch(path: str):
        return table.get(path, (False, None, "HTTP 404"))

    return asyncio.run(fw.detect(fetch))


@pytest.fixture
def collector() -> PrometheusCollector:
    return PrometheusCollector(Settings(), client=None)  # type: ignore[arg-type]


# ===========================================================================
# 1. 数据表完整性：有 CAP_METRICS 的框架必须给出指标映射
# ===========================================================================
def test_metrics_capable_specs_have_series_map():
    """声明了 CAP_METRICS 的框架必须提供指标映射，否则能力是空头支票。"""
    for spec in fw.SPECS:
        if fw.CAP_METRICS in spec.capabilities:
            assert spec.metrics_map, f"{spec.id} 声明了 CAP_METRICS 却没有 metrics_map"


def test_every_series_name_uses_declared_prefix():
    """映射里的每个 series 名都必须带自己的前缀 —— 防止抄错框架。"""
    for spec in fw.SPECS:
        for concept, names in spec.metrics_map.items():
            for name in names:
                assert name.startswith(spec.metrics_prefix), f"{spec.id} 的 {concept} 用了别的前缀：{name}"


def test_detected_info_carries_metrics_map():
    """识别结果必须把映射带给采集器（否则 set_series_map 拿到空表）。"""
    vllm = _detect(VLLM_TABLE)
    assert vllm.id == "vllm"
    assert vllm.metrics_map == dict(fw.SPECS_BY_ID["vllm"].metrics_map)
    assert vllm.as_dict()["metrics_concepts"], "快照应能说明哪些指标概念可用"

    sglang = _detect(SGLANG_TABLE)
    assert sglang.id == "sglang"
    assert sglang.metrics_map


# ===========================================================================
# 2. D2 回归：vLLM / SGLang 的 series 必须能被解析与取值
# ===========================================================================
def test_vllm_series_are_filtered_out_by_default_map(collector):
    """修复前行为复现：默认（llama）映射下，vllm:* 一条也认不出来。"""
    assert parse_prometheus(VLLM_TEXT, collector._names) == {}


def test_vllm_series_parsed_with_framework_map(collector):
    """切到 vLLM 映射后：整段文本能被解析，且概念取值正确。"""
    info = _detect(VLLM_TABLE)
    collector.set_series_map(info.metrics_map)
    collector.values = parse_prometheus(VLLM_TEXT, collector._names)
    assert collector.values, "vLLM 的指标文本不应被全部过滤"
    assert collector.tokens_predicted_total() == 34000
    assert collector.requests_deferred() == 7
    # 投机解码接受率 = accepted / draft
    assert collector.mtp_accept() == pytest.approx(820 / 1000)
    # vLLM 没有"生成秒数"计数器 → 不猜，返回 None
    assert collector.decode_tps() is None
    assert collector.cache_hit_ratio() is None


def test_sglang_series_parsed_with_framework_map(collector):
    info = _detect(SGLANG_TABLE)
    collector.set_series_map(info.metrics_map)
    collector.values = parse_prometheus(SGLANG_TEXT, collector._names)
    assert collector.tokens_predicted_total() == 2100
    assert collector.requests_deferred() == 5  # sglang:num_queue_reqs
    assert collector.mtp_accept() is None  # 未映射该概念 → 不猜


def test_llama_series_unchanged(collector):
    """llama.cpp 行为必须一字不变（默认映射就是它）。"""
    collector.values = parse_prometheus(LLAMA_TEXT, collector._names)
    assert collector.tokens_predicted_total() == 1198564
    assert collector.requests_deferred() == 0
    assert collector.decode_tps() == pytest.approx(1198564 / 17600)
    assert collector.mtp_accept() == pytest.approx(422 / 516)
    assert collector.cache_hit_ratio() == pytest.approx(18000 / (18000 + 42000))


def test_unknown_framework_falls_back_to_llama_map(collector):
    """未知框架（空映射）回落 llama 默认表，而不是一条都认不出来。"""
    collector.set_series_map({})
    assert "llamacpp:tokens_predicted_total" in collector._names


def test_no_match_reason_distinguishes_unknown_names(collector):
    """有数据但名字不认识时，要给出可诊断的原因（而不是笼统的失败）。"""
    collector.set_series_map(_detect(VLLM_TABLE).metrics_map)
    reason = collector._no_match_reason("vllm:brand_new_metric 1\n")
    assert "未匹配到已知指标名" in reason
    assert "vllm:" in reason
    # 完全没有同前缀数据 → 用通用文案
    assert collector._no_match_reason("other:thing 1\n") == "metrics endpoint returned no known series"


# ===========================================================================
# 3. D1 回归：采集开关必须由框架能力决定，而不是 /props
# ===========================================================================
def _container(tmp_path):
    from app.main import build_container

    return build_container(Settings(state_dir=str(tmp_path / "state")))


def test_vllm_metrics_enabled_even_without_props(tmp_path):
    """**D1 的核心判据**：vLLM 没有 /props，指标仍必须被视为可用。"""
    c = _container(tmp_path)
    assert c.props.metrics_enabled is False, "前提：没有 /props 时该开关为 False"

    c.aggregator.set_framework(_detect(VLLM_TABLE))
    assert c.aggregator._metrics_enabled() is True, "vLLM 声明了 CAP_METRICS，应采集"
    assert c.metrics.available is not False, "不应被标记为不可用"


def test_sglang_metrics_enabled_without_props(tmp_path):
    c = _container(tmp_path)
    c.aggregator.set_framework(_detect(SGLANG_TABLE))
    assert c.aggregator._metrics_enabled() is True


def test_ollama_metrics_disabled_with_reason(tmp_path):
    """Ollama 没有 Prometheus 接口 → 不采集，并给出**具体**原因。"""
    c = _container(tmp_path)
    c.aggregator.set_framework(_detect(OLLAMA_TABLE))
    assert c.aggregator._metrics_enabled() is False
    assert c.metrics.available is False
    assert "不提供 Prometheus 指标接口" in (c.metrics.disabled_reason or "")


def test_llama_still_follows_props_switch(tmp_path):
    """llama.cpp 有 /props，仍以 endpoint_metrics 为权威开关（不回归）。"""
    c = _container(tmp_path)
    c.aggregator.set_framework(_detect(LLAMA_TABLE))
    # 设置里没有真去采集 /props，属性直接来自 props 字典
    c.props.props["endpoint_metrics"] = False
    assert c.aggregator._metrics_enabled() is False
    c.props.props["endpoint_metrics"] = True
    assert c.aggregator._metrics_enabled() is True


def test_unknown_framework_falls_back_to_props(tmp_path):
    """尚未识别框架时保持历史行为：只看 /props。"""
    c = _container(tmp_path)
    assert c.aggregator.framework is None
    assert c.aggregator._metrics_enabled() is False


def test_logs_stale_only_when_follower_stopped(tmp_path):
    """「日志陈旧」应表示数据源不可用，而不是"最近没有新日志"。

    vLLM 把日志写到文件，journald 里只有启动几行；若按"120 秒无新行"判断，
    logs 会永久 stale（实测）。
    """
    c = _container(tmp_path)
    c.journal.running = True
    assert c.aggregator._build(0).stale["logs"] is False
    c.journal.running = False
    assert c.aggregator._build(0).stale["logs"] is True


# ===========================================================================
# 4. vLLM 专属：KV 缓存占用 / tokens/s / 「接口通但没指标」
# ===========================================================================
class _FakeMetricsClient:
    def __init__(self, text: str = "", code: int = 200):
        self._text = text
        self._code = code
        self.calls = 0

    async def metrics(self):
        self.calls += 1
        if self._code != 200:
            return False, "", f"HTTP {self._code}"
        return True, self._text, None


def test_vllm_kv_usage_from_metrics(collector):
    """vLLM 没有 /slots，但 /metrics 上报缓存占用 —— 不应显示 0%。"""
    collector.set_series_map(_detect(VLLM_TABLE).metrics_map)
    text = "vllm:kv_cache_usage_perc 42.5\nvllm:generation_tokens_total 1000\n"
    collector.values = parse_prometheus(text, collector._names)
    assert collector.kv_usage_pct() == pytest.approx(42.5)


def test_kv_usage_ratio_is_scaled_to_percent(collector):
    """有的版本上报 0~1 的比例，必须换算成百分比。"""
    collector.set_series_map(_detect(VLLM_TABLE).metrics_map)
    collector.values = {"vllm:kv_cache_usage_perc": 0.42}
    assert collector.kv_usage_pct() == pytest.approx(42.0)


def test_labeled_series_are_parsed(collector):
    """vLLM 的指标几乎都带标签，解析时必须剥离 ``{...}``。

    真实缺陷：不剥离时 series 名变成
    ``vllm:generation_tokens_total{model_name="..."}``，一条也匹配不上，
    界面表现为"接口有响应但没有已知指标"。
    """
    collector.set_series_map(dict(fw.SPECS_BY_ID["vllm"].metrics_map))
    text = (
        'vllm:generation_tokens_total{model_name="m"} 34.0\n'
        'vllm:num_requests_running{model_name="m"} 2.0\n'
        'vllm:kv_cache_usage_perc{model_name="m"} 12.5\n'
    )
    collector.values = parse_prometheus(text, collector._names)
    assert collector.tokens_predicted_total() == 34.0
    assert collector.requests_running() == 2.0
    assert collector.kv_usage_pct() == pytest.approx(12.5)


def test_tokens_per_second_from_counter_delta(collector):
    """没有 *_seconds_total 的框架：用计数器增量算 tokens/s。"""
    collector.set_series_map(_detect(VLLM_TABLE).metrics_map)
    name = "vllm:generation_tokens_total"
    collector._update_rate({name: 100.0}, now=10.0)
    assert collector.tokens_per_second() is None, "首次采样没有基准，不能猜"
    collector._update_rate({name: 300.0}, now=12.0)
    assert collector.tokens_per_second() == pytest.approx(100.0)
    # 计数器归零（服务重启）：不产生负速率，也不保留陈旧值
    collector._update_rate({name: 10.0}, now=14.0)
    assert collector.tokens_per_second() == pytest.approx(100.0)


async def test_endpoint_ok_but_no_known_series_is_not_an_error(collector):
    """接口 200、但没有已知 series：应标为可用 + 提示，而不是每拍失败。"""
    collector.client = _FakeMetricsClient("vllm:some_future_metric 1\n")
    # 异步测试里不能用 asyncio.run(detect())，直接用 SPECS 的映射
    collector.set_series_map(dict(fw.SPECS_BY_ID["vllm"].metrics_map))
    assert await collector.collect() is True
    assert collector.available is True
    assert collector.disabled_reason is None
    assert collector.note and "未匹配到已知指标名" in collector.note
    assert collector.state.stale is False, "不应把「没指标」记成 stale"


async def test_endpoint_without_matching_prefix_still_fails(collector):
    """连前缀都对不上（例如根本没开指标）仍然算失败，不能假装可用。"""
    collector.client = _FakeMetricsClient("other_metric 1\n")
    collector.set_series_map(dict(fw.SPECS_BY_ID["vllm"].metrics_map))
    for _ in range(3):  # stale 需要连续多次失败
        assert await collector.collect() is False
    assert collector.state.stale is True
