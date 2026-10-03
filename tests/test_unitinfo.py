"""systemd unit 参数解析测试（方案 TASK-05 / 6.4.4）。

这是「配置徽标」的权威数据源：/props 只给默认值（实测 spec_types = "none"），
/slots 空闲时 params 为空，只有 unit 的 ExecStart 反映真实运行参数。
"""

from __future__ import annotations

from app.services.unitinfo import UnitConfig, parse_unit_text, read_unit

REAL_UNIT = """\
[Unit]
Description=LLaMA.cpp Server (qwen3-27b Q4_K_M, MTP, tensor-split, 128K ctx, f16 KV, 6 slots)
After=network.target

[Service]
Type=simple
User=llmops
ExecStart=/home/llmops/llama.cpp/build-v050/bin/llama-server -m /home/llmops/models/qwen3-27b-instruct-q4_k_m.gguf -ngl 99 -sm tensor -ts 1,1 -c 131072 --parallel 6 -kvu --port 8080 --host 0.0.0.0 -fa on -fit off --reasoning off --spec-type draft-mtp --spec-draft-n-max 2
Restart=always
RestartSec=10
Environment="CUDA_VISIBLE_DEVICES=0,1"

[Install]
WantedBy=multi-user.target
"""

REAL_WITH_METRICS = REAL_UNIT.replace("--spec-draft-n-max 2", "--spec-draft-n-max 2 --metrics")


def test_parse_real_253_unit():
    cfg = parse_unit_text(REAL_UNIT, "llm-infer.service")
    assert cfg.spec_type == "draft-mtp"
    assert cfg.draft_n_max == 2
    assert cfg.flash_attn is True
    assert cfg.tensor_split == "1,1"
    assert cfg.gpu_count == 2
    assert cfg.parallel == 6
    assert cfg.n_ctx == 131072
    assert cfg.n_gpu_layers == 99
    assert cfg.metrics_flag is False
    assert cfg.model_path.endswith("qwen3-27b-instruct-q4_k_m.gguf")
    assert cfg.unit == "llm-infer.service"


def test_metrics_flag_detected():
    assert parse_unit_text(REAL_WITH_METRICS).metrics_flag is True


def test_flash_attn_off():
    text = "[Service]\nExecStart=/x/llama-server -fa off --spec-type none\n"
    cfg = parse_unit_text(text)
    assert cfg.flash_attn is False
    assert cfg.spec_type == "none"


def test_long_option_forms():
    text = (
        "[Service]\n"
        "ExecStart=/x/llama-server --model /m.gguf --ctx-size 8192 --n-gpu-layers 20 "
        "--parallel 3 --tensor-split 1,1,1 --flash-attn on\n"
    )
    cfg = parse_unit_text(text)
    assert cfg.n_ctx == 8192
    assert cfg.n_gpu_layers == 20
    assert cfg.parallel == 3
    assert cfg.tensor_split == "1,1,1"
    assert cfg.gpu_count == 3
    assert cfg.flash_attn is True


def test_multiline_execstart():
    text = (
        "[Service]\n"
        "ExecStart=/x/llama-server \\\n"
        "    -m /m.gguf \\\n"
        "    --spec-type draft-mtp --spec-draft-n-max 4\n"
    )
    cfg = parse_unit_text(text)
    assert cfg.model_path == "/m.gguf"
    assert cfg.spec_type == "draft-mtp"
    assert cfg.draft_n_max == 4


def test_empty_and_garbage_never_raise():
    for text in ("", "[Service]\n", "not a unit", "ExecStart=", "\x00\x01"):
        cfg = parse_unit_text(text)
        assert isinstance(cfg, UnitConfig)
        assert cfg.draft_n_max == 0
        assert cfg.gpu_count == 0


def test_gpu_count_from_tensor_split():
    assert UnitConfig(tensor_split="1,1").gpu_count == 2
    assert UnitConfig(tensor_split="").gpu_count == 0
    assert UnitConfig(tensor_split="1,1,1,1").gpu_count == 4


def test_read_unit_missing_file_returns_default():
    cfg = read_unit("definitely-not-a-unit.service", directories=("/nonexistent",))
    assert cfg.unit == "definitely-not-a-unit.service"
    assert cfg.spec_type == ""
    assert cfg.draft_n_max == 0


def test_runtime_config_prefers_unit_over_props(settings, props_payload, models_payload):
    """回归：/props 说 none、unit 说 draft-mtp 时，徽标必须显示 unit 的值。"""
    import asyncio

    from app.collectors.props import PropsCollector

    class FakeClient:
        async def props(self_inner):
            return True, props_payload, None

        async def models(self_inner):
            return True, models_payload, None

    c = PropsCollector(settings, FakeClient())
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c.collect(force=True))

    # 槽位空闲（无 spec 信息）+ /props 默认 none → 必须靠 unit 兜底
    rt = c.runtime_config(gpu_count=2, unit=parse_unit_text(REAL_UNIT), slot_spec_types="")
    assert rt.spec_types == "draft-mtp"
    assert rt.draft_n_max == 2
    assert rt.tensor_split == "1,1"
    blob = " ".join(rt.badges)
    assert "投机解码 draft-mtp" in blob
    assert "draft 2(+1)" in blob
    assert "tensor-split 1,1" in blob

    # /slots 有更具体的值时优先
    rt2 = c.runtime_config(gpu_count=2, unit=parse_unit_text(REAL_UNIT), slot_spec_types="none,draft-mtp")
    assert rt2.spec_types == "none,draft-mtp"
