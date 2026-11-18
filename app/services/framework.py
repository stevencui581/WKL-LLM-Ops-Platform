"""推理框架自动识别（v0.5 第 1 步）。

**为什么需要这个模块**
    控制台最初按 llama.cpp 的专有接口设计（``/props`` ``/slots`` ``/metrics llamacpp:*``）。
    一旦部署到 ollama / vLLM / SGLang，这些端点并不存在，
    结果是"界面一片空白 + 大量 stale 告警" —— 看起来像控制台坏了，
    实际只是**框架不同**。

    本模块在运行期探测"当前到底是哪个框架、什么版本、支持哪些接口"，
    让上层据此决定：能采就采、不能采就**明确说明不支持**，而不是报错或留空。

**识别策略**
    按优先级依次试探，**先专有信号、后通用信号**：

    1. llama.cpp —— ``/props`` 返回含 ``build_info`` / ``default_generation_settings``
    2. ollama    —— ``/api/version`` 返回含 ``version``
    3. SGLang    —— ``/get_model_info`` 返回含 ``model_path`` / ``model_name``
    4. vLLM      —— ``/version`` 可用 且 ``/v1/models`` 可用
    5. OpenAI 兼容（兜底）—— 仅 ``/v1/models`` 可用
    6. unknown

    实测互斥性良好：llama.cpp 上 ``/version`` ``/api/version`` ``/get_model_info``
    均返回 404，因此不会误判。

**版本号来源（实测确认）**
    * llama.cpp：``/props`` → ``build_info``（形如 ``b11146-7fe450e19``）
      —— 不需要执行二进制，也不需要翻 journal
    * ollama  ：``/api/version`` → ``version``
    * vLLM    ：``/version``（纯文本）
    * SGLang  ：``/get_server_info`` → ``version``

本模块**不直接发起网络请求**，而是接收两个 ``fetch`` 可调用对象 ——
这样识别逻辑可以完全用假数据单测，不需要真起服务。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: fetch 返回 ``(ok, payload, error)``；payload 为 dict 或 str
Fetcher = Callable[[str], Awaitable[tuple[bool, Any, str | None]]]

# ---------------------------------------------------------------- 能力词汇
CAP_PROPS = "props"  # 模型参数 / 配置（llama.cpp /props）
CAP_SLOTS = "slots"  # 槽位级明细（llama.cpp /slots）
CAP_METRICS = "metrics"  # Prometheus 文本指标
CAP_MODELS = "models"  # 模型列表（/v1/models 等）
CAP_HEALTH = "health"  # 健康检查
CAP_VERSION = "version"  # 独立的版极端点
CAP_TAGS = "tags"  # ollama 已拉取模型列表
CAP_PS = "ps"  # ollama 运行中模型

ALL_CAPS = frozenset(
    {CAP_PROPS, CAP_SLOTS, CAP_METRICS, CAP_MODELS, CAP_HEALTH, CAP_VERSION, CAP_TAGS, CAP_PS}
)

# ---------------------------------------------------------------- 指标概念
#: 跨框架统一的指标**概念**（v0.6.1）。
#:
#: 不同框架的 Prometheus series 名字完全不同（``llamacpp:tokens_predicted_total`` /
#: ``vllm:generation_tokens_total`` / ``sglang:generation_tokens_total``），但语义相同。
#: 采集器只认概念，具体名字由各框架的 ``metrics_map`` 提供 ——
#: 这样新增框架时**只加一张映射表**，不用改采集器里的任何判断。
M_REQUESTS_RUNNING = "requests_running"
M_REQUESTS_WAITING = "requests_waiting"
M_TOKENS_GENERATED = "tokens_generated_total"
M_TOKENS_GENERATED_SECONDS = "tokens_generated_seconds_total"
M_TOKENS_PROMPT = "tokens_prompt_total"
M_TOKENS_PROMPT_SECONDS = "tokens_prompt_seconds_total"
M_TOKENS_PROMPT_CACHED = "tokens_prompt_cached_total"
M_SPEC_DRAFT_TOKENS = "spec_draft_tokens_total"
M_SPEC_ACCEPTED_TOKENS = "spec_accepted_tokens_total"


# ---------------------------------------------------------------- 规格定义
@dataclass(frozen=True, slots=True)
class FrameworkSpec:
    """一个推理框架的识别规则。**数据表驱动**：新增框架只需加一项。"""

    id: str
    name_zh: str
    name_en: str
    #: 判定所需路径（必须全部可用）
    require_paths: tuple[str, ...]
    #: 判定谓词：接收 (path, payload) 字典，命中返回 True
    match: tuple[tuple[str, str], ...]  # (path, json_key) —— 该键存在即命中
    #: 版本读取：路径 + 取值方式
    version_path: str = ""
    version_keys: tuple[str, ...] = ()
    version_is_text: bool = False
    capabilities: frozenset[str] = frozenset()
    metrics_prefix: str = ""
    #: Prometheus 指标映射：**概念 → 候选 series 名**（按顺序取第一个存在的）。
    #:
    #: 为什么是"候选列表"而不是单个名字：这些 series 名会随框架版本变化，
    #: 列几个已知写法可以跨版本兼容；一个都匹配不上时如实显示不可用（不猜）。
    metrics_map: Mapping[str, tuple[str, ...]] = field(default_factory=dict, hash=False, repr=False)
    #: 该框架下"槽位/参数"类接口不可用时，界面上应显示的解释
    note_zh: str = ""
    note_en: str = ""


SPECS: tuple[FrameworkSpec, ...] = (
    FrameworkSpec(
        id="llama.cpp",
        name_zh="llama.cpp（llama-server）",
        name_en="llama.cpp (llama-server)",
        require_paths=("/props",),
        match=(
            ("/props", "build_info"),
            ("/props", "default_generation_settings"),
            ("/props", "total_slots"),
        ),
        version_path="/props",
        version_keys=("build_info", "version"),
        capabilities=frozenset({CAP_PROPS, CAP_SLOTS, CAP_METRICS, CAP_MODELS, CAP_HEALTH}),
        metrics_prefix="llamacpp:",
        metrics_map={
            M_REQUESTS_RUNNING: ("llamacpp:requests_processing",),
            M_REQUESTS_WAITING: ("llamacpp:requests_deferred",),
            M_TOKENS_GENERATED: ("llamacpp:tokens_predicted_total",),
            M_TOKENS_GENERATED_SECONDS: ("llamacpp:tokens_predicted_seconds_total",),
            M_TOKENS_PROMPT: ("llamacpp:prompt_tokens_total",),
            M_TOKENS_PROMPT_SECONDS: ("llamacpp:prompt_seconds_total",),
            M_TOKENS_PROMPT_CACHED: ("llamacpp:prompt_tokens_cached_total",),
            M_SPEC_DRAFT_TOKENS: ("llamacpp:spec_decode_num_draft_tokens_total",),
            M_SPEC_ACCEPTED_TOKENS: ("llamacpp:spec_decode_num_accepted_tokens_total",),
        },
        note_zh="llama.cpp 提供 /props 与 /slots，可采集槽位级明细",
        note_en="llama.cpp exposes /props and /slots, so per-slot detail is available",
    ),
    FrameworkSpec(
        id="ollama",
        name_zh="Ollama",
        name_en="Ollama",
        require_paths=("/api/version",),
        match=(("/api/version", "version"),),
        version_path="/api/version",
        version_keys=("version",),
        capabilities=frozenset({CAP_VERSION, CAP_MODELS, CAP_HEALTH, CAP_TAGS, CAP_PS}),
        metrics_prefix="",
        note_zh="Ollama 不提供 /props 与 /slots，槽位明细不可用；模型信息取自 /api/tags",
        note_en="Ollama has no /props or /slots; per-slot detail is unavailable. Model info comes from /api/tags",
    ),
    FrameworkSpec(
        id="sglang",
        name_zh="SGLang",
        name_en="SGLang",
        require_paths=("/get_model_info",),
        match=(
            ("/get_model_info", "model_path"),
            ("/get_model_info", "model_name"),
            ("/get_model_info", "model"),
        ),
        version_path="/get_server_info",
        version_keys=("version",),
        capabilities=frozenset({CAP_MODELS, CAP_METRICS, CAP_HEALTH, CAP_VERSION}),
        metrics_prefix="sglang:",
        metrics_map={
            M_REQUESTS_RUNNING: ("sglang:num_running_reqs",),
            M_REQUESTS_WAITING: ("sglang:num_queue_reqs",),
            M_TOKENS_GENERATED: ("sglang:generation_tokens_total",),
            M_TOKENS_PROMPT: ("sglang:prompt_tokens_total",),
        },
        note_zh="SGLang 不提供 /slots，槽位明细不可用；指标前缀为 sglang:",
        note_en="SGLang has no /slots; metrics use the sglang: prefix",
    ),
    FrameworkSpec(
        id="vllm",
        name_zh="vLLM",
        name_en="vLLM",
        require_paths=("/version", "/v1/models"),
        match=(),
        version_path="/version",
        version_keys=(),
        version_is_text=True,
        capabilities=frozenset({CAP_MODELS, CAP_METRICS, CAP_HEALTH, CAP_VERSION}),
        metrics_prefix="vllm:",
        metrics_map={
            M_REQUESTS_RUNNING: ("vllm:num_requests_running",),
            M_REQUESTS_WAITING: ("vllm:num_requests_waiting",),
            M_TOKENS_GENERATED: ("vllm:generation_tokens_total",),
            M_TOKENS_PROMPT: ("vllm:prompt_tokens_total",),
            # 投机解码：vLLM 早期版本带 ``spec_decode_`` 前缀，新版本改为
            # ``spec_decode_num_*``；两种都列上，跨版本兼容。
            M_SPEC_DRAFT_TOKENS: (
                "vllm:spec_decode_num_draft_tokens_total",
                "vllm:spec_decode_draft_tokens_total",
            ),
            M_SPEC_ACCEPTED_TOKENS: (
                "vllm:spec_decode_num_accepted_tokens_total",
                "vllm:spec_decode_accepted_tokens_total",
            ),
        },
        note_zh="vLLM 不提供 /slots，槽位明细不可用；指标前缀为 vllm:",
        note_en="vLLM has no /slots; metrics use the vllm: prefix",
    ),
)

#: 默认指标映射：框架**尚未识别**时按 llama.cpp 试一次（历史唯一验证过的框架）。
#: 识别成功后会由 ``FrameworkInfo.metrics_map`` 覆盖。
DEFAULT_METRICS_MAP: Mapping[str, tuple[str, ...]] = next(s.metrics_map for s in SPECS if s.id == "llama.cpp")

#: 通用兜底：只认 OpenAI 兼容接口
OPENAI_COMPATIBLE = FrameworkSpec(
    id="openai-compatible",
    name_zh="OpenAI 兼容服务（未识别具体框架）",
    name_en="OpenAI-compatible server (framework not identified)",
    require_paths=("/v1/models",),
    match=(),
    capabilities=frozenset({CAP_MODELS, CAP_HEALTH}),
    metrics_prefix="",
    note_zh="仅识别到 OpenAI 兼容接口，模型参数与槽位明细不可用",
    note_en="Only an OpenAI-compatible API was found; model params and per-slot detail are unavailable",
)

UNKNOWN = FrameworkSpec(
    id="unknown",
    name_zh="未识别（推理服务可能未启动或接口不兼容）",
    name_en="Not identified (service down or API incompatible)",
    require_paths=(),
    match=(),
    capabilities=frozenset(),
    metrics_prefix="",
    note_zh="无法识别推理框架，所有依赖推理服务接口的指标都不可用",
    note_en="Inference framework not identified; all metrics that depend on its API are unavailable",
)

SPECS_BY_ID = {s.id: s for s in (*SPECS, OPENAI_COMPATIBLE, UNKNOWN)}


# ---------------------------------------------------------------- 结果模型
@dataclass
class FrameworkInfo:
    id: str = "unknown"
    name_zh: str = UNKNOWN.name_zh
    name_en: str = UNKNOWN.name_en
    version: str = ""
    version_source: str = "unknown"  # 形如 http:/api/version
    build: str = ""  # 额外构建信息（commit 等）
    capabilities: list[str] = field(default_factory=list)
    metrics_prefix: str = ""
    #: 指标概念 → 候选 series 名（由 SPECS 注入；采集器据此取值）
    metrics_map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    note_zh: str = ""
    note_en: str = ""
    confidence: str = "unknown"  # exact | fallback | unknown
    detected_at: float = 0.0
    probes: dict[str, int] = field(default_factory=dict)  # path -> HTTP 状态（诊断用）

    def supports(self, cap: str) -> bool:
        return cap in self.capabilities

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": {"zh": self.name_zh, "en": self.name_en},
            "version": self.version,
            "version_source": self.version_source,
            "build": self.build,
            "capabilities": sorted(self.capabilities),
            "metrics_prefix": self.metrics_prefix,
            #: 已映射的指标概念（前端/诊断可用于说明"哪些指标可用"）
            "metrics_concepts": sorted(self.metrics_map),
            "note": {"zh": self.note_zh, "en": self.note_en},
            "confidence": self.confidence,
            "detected_at": self.detected_at,
            "probes": self.probes,
        }


# ---------------------------------------------------------------- 版本归一
#: llama.cpp 的 build_info 形如 ``b11146-7fe450e19``
RE_LLAMA_BUILD = re.compile(r"^b?(\d+)(?:-([0-9a-f]{6,40}))?$", re.I)


def normalize_version(version_id: str, raw: Any) -> tuple[str, str]:
    """把原始版本信息归一为 ``(version, build)``。

    * llama.cpp：``b11146-7fe450e19`` → ``("b11146", "7fe450e19")``
    * 其它：原样返回文本版本，build 为空
    """
    text = str(raw or "").strip()
    if not text:
        return "", ""
    if version_id == "llama.cpp":
        m = RE_LLAMA_BUILD.match(text)
        if m:
            return f"b{m.group(1)}", (m.group(2) or "")
        return text, ""
    # 去掉可能的 v 前缀，保留原样更利于对照官方文档
    return text, ""


def _pick_keys(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None
    for k in keys:
        if k in payload and payload[k] not in (None, ""):
            return payload[k]
    # 兼容嵌套：vLLM/SGLang 有时把版本放在 data/version 下
    for parent in ("data", "info", "server", "model_info"):
        sub = payload.get(parent)
        if isinstance(sub, dict):
            for k in keys:
                if k in sub and sub[k] not in (None, ""):
                    return sub[k]
    return None


def _matches(spec: FrameworkSpec, payloads: dict[str, Any]) -> bool:
    """判定是否命中该框架。"""
    for path in spec.require_paths:
        if path not in payloads:
            return False
    if not spec.match:
        return True  # 仅要求端点可用（如 vLLM、OpenAI 兼容）
    for path, key in spec.match:
        payload = payloads.get(path)
        if isinstance(payload, dict) and key in payload:
            return True
    return False


# ---------------------------------------------------------------- 识别入口
async def detect(fetch: Fetcher, *, timeout_paths: tuple[str, ...] | None = None) -> FrameworkInfo:
    """探测当前推理框架。

    ``fetch(path)`` 返回 ``(ok, payload, error)``；payload 为 dict 或 str。
    探测失败的路径不会出现在 ``payloads`` 里，也就不会命中对应框架。
    """
    t0 = time.monotonic()
    info = FrameworkInfo(detected_at=time.time())

    # 一次性把所有候选端点问一遍（并发由调用方决定，这里顺序执行、数量很少）
    paths: list[str] = []
    for spec in (*SPECS, OPENAI_COMPATIBLE):
        for p in spec.require_paths:
            if p not in paths:
                paths.append(p)
    if timeout_paths:
        paths = [p for p in paths if p in timeout_paths]

    payloads: dict[str, Any] = {}
    for path in paths:
        ok, payload, err = await fetch(path)
        info.probes[path] = 200 if ok else 0
        if ok:
            payloads[path] = payload
        elif err:
            log.debug("framework probe %s failed: %s", path, err)

    # 按优先级匹配
    for spec in SPECS:
        if _matches(spec, payloads):
            _apply(info, spec, payloads, confidence="exact")
            await _read_version(info, spec, fetch)
            log.info(
                "inference framework detected: %s %s (%.0f ms, probes=%s)",
                info.id,
                info.version or "-",
                (time.monotonic() - t0) * 1000,
                info.probes,
            )
            return info

    if _matches(OPENAI_COMPATIBLE, payloads):
        _apply(info, OPENAI_COMPATIBLE, payloads, confidence="fallback")
        log.info("inference framework: OpenAI-compatible fallback (probes=%s)", info.probes)
        return info

    _apply(info, UNKNOWN, payloads, confidence="unknown")
    log.warning("inference framework not identified (probes=%s)", info.probes)
    return info


def _apply(info: FrameworkInfo, spec: FrameworkSpec, payloads: dict[str, Any], *, confidence: str) -> None:
    info.id = spec.id
    info.name_zh = spec.name_zh
    info.name_en = spec.name_en
    info.capabilities = sorted(spec.capabilities)
    info.metrics_prefix = spec.metrics_prefix
    info.metrics_map = dict(spec.metrics_map)
    info.note_zh = spec.note_zh
    info.note_en = spec.note_en
    info.confidence = confidence


async def _read_version(info: FrameworkInfo, spec: FrameworkSpec, fetch: Fetcher) -> None:
    """读取并归一版本号。读不到就如实留空（不编造）。"""
    if not spec.version_path:
        info.version_source = "unknown"
        return
    ok, payload, err = await fetch(spec.version_path)
    info.probes[spec.version_path] = 200 if ok else 0
    if not ok:
        info.version_source = "unknown"
        log.debug("version probe %s failed: %s", spec.version_path, err)
        return

    raw: Any = None
    if spec.version_is_text and isinstance(payload, str):
        raw = payload.strip()
    else:
        raw = _pick_keys(payload, spec.version_keys)
        if raw is None and isinstance(payload, str):
            raw = payload.strip()
    if raw is None:
        info.version_source = "unknown"
        return

    version, build = normalize_version(spec.id, raw)
    if not version:
        # 端点通了但内容为空/不可解析 —— 如实标注为 unknown，不谎称"已获取"
        info.version_source = "unknown"
        return
    info.version = version
    if build and not info.build:
        info.build = build
    info.version_source = f"http:{spec.version_path}"


# ---------------------------------------------------------------- 便捷判定
def supports(info: FrameworkInfo | None, cap: str) -> bool:
    """``info`` 为 None（尚未识别）时按"支持"处理，避免启动瞬间误关采集。"""
    if info is None:
        return True
    return info.supports(cap)


def capability_summary(info: FrameworkInfo) -> str:
    return f"{info.id} {info.version or '?'} [{','.join(sorted(info.capabilities)) or 'none'}]"
