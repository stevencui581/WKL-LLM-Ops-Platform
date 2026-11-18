"""推理框架自动识别测试（v0.5 第 1 步）。

用**假 HTTP 响应**覆盖 4 种目标框架 + 兜底 + 未识别，
保证换环境部署时能正确识别框架与版本号 —— 而不是只在 llama.cpp 上能用。

真实响应样本来自各框架官方文档与实测（llama.cpp 部分为 目标 上实采）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import framework as fw

# ===========================================================================
# 各框架的假响应（贴近真实形态）
# ===========================================================================
LLAMA_CPP = {
    "/props": (
        True,
        {
            "build_info": "b11146-7fe450e19",
            "model_path": "/srv/models/qwen3-27b-q4_k_m.gguf",
            "model_ftype": "Q4_K - Medium",
            "total_slots": 6,
            "default_generation_settings": {"n_ctx": 131072, "params": {"temperature": 1.0}},
            "endpoint_slots": True,
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

OLLAMA = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "llama3.2"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (True, {"version": "0.5.4"}, None),
    "/api/tags": (True, {"models": [{"name": "llama3.2:latest"}]}, None),
    "/get_model_info": (False, None, "HTTP 404"),
}

VLLM = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "meta-llama/Llama-3-8B"}]}, None),
    "/version": (True, "0.6.3.post1", None),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (False, None, "HTTP 404"),
}

SGLANG = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "qwen2.5-7b"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (True, {"model_path": "/models/qwen2.5-7b", "is_generation": True}, None),
    "/get_server_info": (True, {"version": "0.4.6", "model_path": "/models/qwen2.5-7b"}, None),
}

OPENAI_ONLY = {
    "/props": (False, None, "HTTP 404"),
    "/slots": (False, None, "HTTP 404"),
    "/health": (True, "", None),
    "/v1/models": (True, {"object": "list", "data": [{"id": "some-model"}]}, None),
    "/version": (False, None, "HTTP 404"),
    "/api/version": (False, None, "HTTP 404"),
    "/get_model_info": (False, None, "HTTP 404"),
}

NOTHING = dict.fromkeys(
    ("/props", "/slots", "/health", "/v1/models", "/version", "/api/version", "/get_model_info"),
    (False, None, "connection refused"),
)


def _fetch(table: dict, record: list | None = None):
    async def f(path: str):
        if record is not None:
            record.append(path)
        return table.get(path, (False, None, "HTTP 404"))

    return f


def _detect(table: dict, record: list | None = None) -> fw.FrameworkInfo:
    # 用 asyncio.run 而不是裸 new_event_loop：后者不关闭会留下未回收的
    # selector 文件描述符，pytest 会报 PytestUnraisableExceptionWarning。
    return asyncio.run(fw.detect(_fetch(table, record)))


# ===========================================================================
# 1. 四种目标框架都能识别
# ===========================================================================
def test_detect_llama_cpp():
    info = _detect(LLAMA_CPP)
    assert info.id == "llama.cpp"
    assert info.confidence == "exact"
    assert info.version == "b11146"
    assert info.build == "7fe450e19"
    assert info.version_source == "http:/props"
    assert info.metrics_prefix == "llamacpp:"
    for cap in (fw.CAP_PROPS, fw.CAP_SLOTS, fw.CAP_METRICS, fw.CAP_MODELS, fw.CAP_HEALTH):
        assert info.supports(cap), cap
    assert "llama.cpp" in info.name_en


def test_detect_ollama():
    info = _detect(OLLAMA)
    assert info.id == "ollama"
    assert info.version == "0.5.4"
    assert info.version_source == "http:/api/version"
    assert info.supports(fw.CAP_VERSION) and info.supports(fw.CAP_TAGS)
    # ollama 没有槽位与 /props
    assert not info.supports(fw.CAP_SLOTS)
    assert not info.supports(fw.CAP_PROPS)
    assert info.note_zh and info.note_en, "必须给出「该框架不支持什么」的说明"


def test_detect_vllm():
    info = _detect(VLLM)
    assert info.id == "vllm"
    assert info.version == "0.6.3.post1"
    assert info.metrics_prefix == "vllm:"
    assert info.supports(fw.CAP_METRICS)
    assert not info.supports(fw.CAP_SLOTS)


def test_detect_vllm_version_as_json():
    """部分 vLLM 构建的 /version 返回 JSON 而不是纯文本（实测 2080Ti 定制版）。

    旧实现只按纯文本读，遇到 JSON 就得到空版本号；现在两种都要能读。
    """
    table = dict(VLLM)
    table["/version"] = (True, {"version": "0.2.2.post3"}, None)
    info = _detect(table)
    assert info.id == "vllm"
    assert info.version == "0.2.2.post3"
    assert info.version_source == "http:/version"


def test_detect_sglang():
    info = _detect(SGLANG)
    assert info.id == "sglang"
    assert info.version == "0.4.6"
    assert info.version_source == "http:/get_server_info"
    assert info.metrics_prefix == "sglang:"
    assert not info.supports(fw.CAP_SLOTS)


def test_detect_openai_compatible_fallback():
    info = _detect(OPENAI_ONLY)
    assert info.id == "openai-compatible"
    assert info.confidence == "fallback"
    assert info.supports(fw.CAP_MODELS)
    assert not info.supports(fw.CAP_SLOTS)


def test_detect_unknown_when_nothing_responds():
    info = _detect(NOTHING)
    assert info.id == "unknown"
    assert info.confidence == "unknown"
    assert info.capabilities == []
    assert info.version == "", "识别不到就留空，不得编造版本"


# ===========================================================================
# 2. 优先级：专有信号优先于通用信号
# ===========================================================================
def test_llama_cpp_wins_over_openai_compatible():
    """llama.cpp 也提供 /v1/models，但必须识别为 llama.cpp 而不是 OpenAI 兼容。"""
    info = _detect(LLAMA_CPP)
    assert info.id == "llama.cpp", "专有信号必须优先于通用兜底"


def test_sglang_wins_over_openai_compatible():
    info = _detect(SGLANG)
    assert info.id == "sglang"


def test_ollama_not_misdetected_as_llama_cpp():
    """ollama 上 /props 为 404，不得误判为 llama.cpp。"""
    info = _detect(OLLAMA)
    assert info.id != "llama.cpp"


def test_vllm_not_misdetected_as_sglang():
    """vLLM 没有 /get_model_info，不得误判为 SGLang。"""
    info = _detect(VLLM)
    assert info.id != "sglang"


# ===========================================================================
# 3. 版本归一
# ===========================================================================
@pytest.mark.parametrize(
    "raw,ver,build",
    [
        ("b11146-7fe450e19", "b11146", "7fe450e19"),
        ("b11146", "b11146", ""),
        ("11146-7fe450e19", "b11146", "7fe450e19"),
        ("", "", ""),
    ],
)
def test_normalize_llama_build_info(raw, ver, build):
    assert fw.normalize_version("llama.cpp", raw) == (ver, build)


@pytest.mark.parametrize(
    "vid,raw",
    [
        ("ollama", "0.5.4"),
        ("vllm", "0.6.3.post1"),
        ("sglang", "0.4.6"),
    ],
)
def test_normalize_other_frameworks_keep_text(vid, raw):
    assert fw.normalize_version(vid, raw) == (raw, "")


def test_version_read_from_nested_payload():
    """部分框架把版本放在 data/info 子对象里，必须也能取到。"""
    table = dict(SGLANG)
    table["/get_server_info"] = (True, {"data": {"version": "0.4.7"}}, None)
    info = _detect(table)
    assert info.version == "0.4.7"


def test_version_missing_is_empty_not_fabricated():
    table = dict(VLLM)
    table["/version"] = (True, "   ", None)
    info = _detect(table)
    assert info.id == "vllm"
    assert info.version == ""
    assert info.version_source == "unknown"


# ===========================================================================
# 4. 诊断字段与辅助函数
# ===========================================================================
def test_probes_recorded_for_diagnosis():
    info = _detect(LLAMA_CPP)
    assert "/props" in info.probes
    assert info.probes["/props"] == 200
    assert info.probes["/version"] == 0, "404 的端点应记录为不可用"


def test_as_dict_is_language_neutral():
    """对外形态必须把中英文都给出，由前端按语言挑（数据与展示分离）。"""
    d = _detect(SGLANG).as_dict()
    assert set(d["name"]) == {"zh", "en"}
    assert set(d["note"]) == {"zh", "en"}
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in d["name"]["en"])
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in d["note"]["en"])
    assert d["capabilities"] == sorted(d["capabilities"])


def test_supports_none_means_yes():
    """尚未识别（None）时按支持处理，避免启动瞬间误关所有采集。"""
    assert fw.supports(None, fw.CAP_SLOTS) is True
    assert fw.supports(_detect(OLLAMA), fw.CAP_SLOTS) is False


def test_capability_summary():
    s = fw.capability_summary(_detect(VLLM))
    assert "vllm" in s and "0.6.3.post1" in s


# ===========================================================================
# 5. 新增框架只需加数据表项（不写 if-else）
# ===========================================================================
def test_specs_are_data_driven():
    """四个目标框架都必须在 SPECS 表里，且各自声明能力与指标前缀。"""
    ids = {s.id for s in fw.SPECS}
    assert {"llama.cpp", "ollama", "sglang", "vllm"} <= ids
    for spec in fw.SPECS:
        assert spec.name_zh and spec.name_en
        assert spec.capabilities, f"{spec.id} 未声明任何能力"
        if spec.id != "llama.cpp":
            assert spec.note_zh and spec.note_en, f"{spec.id} 缺少不支持项的说明"


def test_no_hardcoded_framework_in_collectors():
    """采集器不得写死框架名 —— 框架信息必须来自识别模块。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    offenders: list[str] = []
    for p in root.rglob("*.py"):
        if p.name == "framework.py":
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = ln.split("#", 1)[0]
            if re.search(r'"(vllm|ollama|sglang)"', code, re.I):
                offenders.append(f"{p.name}:{i}")
    assert not offenders, f"以下位置写死了框架名：{offenders}"
