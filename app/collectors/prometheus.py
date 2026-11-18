"""Collector-E：/metrics Prometheus 采集器（方案 TASK-09；v0.6.1 多框架化）。

关键行为：
  * **指标名由框架提供**（``FrameworkInfo.metrics_map``）：llama.cpp 是
    ``llamacpp:`` 前缀，vLLM 是 ``vllm:``，SGLang 是 ``sglang:`` ——
    本模块只认**概念**（生成 token 总量、排队请求数…），不认具体前缀；
  * ``/props`` 的 ``endpoint_metrics=false`` 时**不发起任何请求**（避免每 2 秒打一次无效请求）；
  * 若误发起并收到 501，则识别 ``not_supported_error`` 并**永久降级**；
  * 命名坑：生成计数是 ``tokens_predicted_total``，而生成速率是 ``predicted_tokens_seconds``；
  * 缓存命中率 = cached / (cached + prefill)，不是 cached / prefill；
  * 一个概念都匹配不上时**如实报告**（不猜、不编造），并提示可能的原因。

**为什么改成概念映射（v0.6.1 修复）**

    原先模块里写死了 ``WANTED = ("llamacpp:...",)``，于是即使框架识别为 vLLM/SGLang，
    ``/metrics`` 返回的 ``vllm:*`` / ``sglang:*`` 序列也全部被过滤掉 ——
    表现为"接口明明有数据，界面却一直显示指标不可用"。
    现在把名字表放回框架定义（数据表驱动），新增框架只需加一张映射。
"""

from __future__ import annotations

import time
from collections.abc import Collection, Iterable, Mapping

from ..adapters.llama import LlamaClient
from ..config import Settings
from ..services.framework import (
    DEFAULT_METRICS_MAP,
    M_REQUESTS_WAITING,
    M_SPEC_ACCEPTED_TOKENS,
    M_SPEC_DRAFT_TOKENS,
    M_TOKENS_GENERATED,
    M_TOKENS_GENERATED_SECONDS,
    M_TOKENS_PROMPT,
    M_TOKENS_PROMPT_CACHED,
)
from .base import CollectorState, to_num

#: ``enabled=False`` 且调用方没给原因时的默认文案（保持与旧版一致，含「未启用」）。
DEFAULT_DISABLED_REASON = "服务端未启用指标接口（/props endpoint_metrics=false）"


def _names_of(mapping: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    """映射表里出现过的全部 series 名（用于解析时过滤）。"""
    return frozenset(name for names in mapping.values() for name in names)


def parse_prometheus(text: str, names: Collection[str] | None = None) -> dict[str, float]:
    """解析 Prometheus 文本格式，只保留**已知 series**（均无标签）。

    ``names`` 为当前框架的 series 名单；缺省时用 llama.cpp 的默认表
    （框架尚未识别时的历史行为）。
    """
    wanted = frozenset(names) if names is not None else _names_of(DEFAULT_METRICS_MAP)
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition(" ")
        name = name.strip()
        if name not in wanted:
            continue
        v = to_num(value.strip())
        if v is not None:
            out[name] = v
    return out


def _prefixes(names: Iterable[str]) -> tuple[str, ...]:
    """从 series 名提取前缀（``llamacpp:`` / ``vllm:`` …），用于诊断信息。"""
    return tuple(sorted({n.split(":", 1)[0] + ":" for n in names if ":" in n}))


class PrometheusCollector:
    name = "metrics"

    def __init__(self, settings: Settings, client: LlamaClient):
        self.s = settings
        #: 状态键使用 "metrics"，与快照 stale 字典保持一致
        self.state = CollectorState("metrics", settings.stale_after_misses)
        self.client = client
        self.values: dict[str, float] = {}
        self.available: bool | None = None  # None = 未知，True/False = 已探明
        self.disabled_reason: str | None = None
        self._last_ok_mono = 0.0
        #: 当前框架的指标映射（概念 → 候选 series 名）
        self._map: Mapping[str, tuple[str, ...]] = DEFAULT_METRICS_MAP
        self._names: frozenset[str] = _names_of(self._map)

    # ------------------------------------------------------------------ 配置
    def set_series_map(self, mapping: Mapping[str, tuple[str, ...]] | None) -> None:
        """跟随框架识别结果切换指标名映射（v0.6.1）。

        传空映射（未知框架）时回落到 llama.cpp 默认表：这是历史唯一验证过的
        框架，试一次的成本很低，失败会被如实标记为不可用。
        """
        self._map = dict(mapping) if mapping else DEFAULT_METRICS_MAP
        self._names = _names_of(self._map)
        # 换框架后重新探测：之前可能因为"不认识这些指标名"而失败
        if self.available is not True:
            self.available = None
            self.disabled_reason = None

    def mark_disabled(self, reason: str) -> None:
        self.available = False
        self.disabled_reason = reason

    def set_endpoint_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """由上层（聚合器）决定是否采集，并可给出**具体原因**。

        关键点：如果之前因为「服务端未启用」而永久降级，那么运维在服务端
        加上 --metrics 并重启后，控制台必须**自己恢复**，不需要重启控制台。
        实测踩过这个坑：不加这段，启用 --metrics 后界面一直显示未启用。

        ``reason`` 由聚合器按框架给出（例如"当前框架不提供 Prometheus 指标"），
        缺省时用 ``DEFAULT_DISABLED_REASON``。
        """
        if not enabled:
            text = reason or DEFAULT_DISABLED_REASON
            if self.available is not False or self.disabled_reason != text:
                self.mark_disabled(text)
            return
        if self.available is False:
            # 重新变为未知，下一次 collect() 会真正去探测
            self.available = None
            self.disabled_reason = None

    # ------------------------------------------------------------------ 采集
    async def collect(self, force_probe: bool = False) -> bool:
        if self.available is False and not force_probe:
            # 已确认不可用：不再发起请求（避免无效流量）
            return False
        t0 = time.monotonic()
        ok, text, err = await self.client.metrics()
        if not ok:
            if err and ("HTTP 501" in err or "not_supported_error" in (text or "")):
                self.mark_disabled("HTTP 501: 服务端未启用 --metrics")
            else:
                self.state.fail(err or "metrics unavailable")
            return False
        values = parse_prometheus(text, self._names)
        if not values:
            self.state.fail(self._no_match_reason(text))
            return False
        self.values = values
        self.available = True
        self.disabled_reason = None
        self._last_ok_mono = time.monotonic()
        self.state.ok((time.monotonic() - t0) * 1000.0)
        return True

    def _no_match_reason(self, text: str) -> str:
        """区分"完全没数据"与"有数据但不是我们认识的名字"——后者要能提示用户。"""
        prefixes = _prefixes(self._names)
        hit = 0
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            name = s.split(" ", 1)[0]
            if prefixes and name.startswith(prefixes):
                hit += 1
        if hit:
            return f"指标接口有响应，但未匹配到已知指标名（已知前缀 {', '.join(prefixes)}；框架版本可能不同）"
        return "metrics endpoint returned no known series"

    # ------------------------------------------------------------------ 取值
    def _val(self, concept: str) -> float | None:
        """按概念取第一个存在的候选 series。"""
        for name in self._map.get(concept, ()):
            v = self.values.get(name)
            if v is not None:
                return v
        return None

    # ---- 派生量（方案 6.2.1）----
    def tokens_predicted_total(self) -> float | None:
        return self._val(M_TOKENS_GENERATED)

    def requests_deferred(self) -> float | None:
        return self._val(M_REQUESTS_WAITING)

    def decode_tps(self) -> float | None:
        """必须用计数器推导；``predicted_tokens_seconds`` 空闲时为 0，不可直接告警。

        没有"生成秒数"计数器的框架（vLLM/SGLang）返回 ``None`` —— 不猜。
        """
        tok = self._val(M_TOKENS_GENERATED)
        sec = self._val(M_TOKENS_GENERATED_SECONDS)
        if tok is None or sec is None or sec <= 0:
            return None
        return tok / sec

    def mtp_accept(self) -> float | None:
        acc = self._val(M_SPEC_ACCEPTED_TOKENS)
        gen = self._val(M_SPEC_DRAFT_TOKENS)
        if acc is None or gen is None or gen <= 0:
            return None
        return acc / gen

    def cache_hit_ratio(self) -> float | None:
        cached = self._val(M_TOKENS_PROMPT_CACHED)
        prefill = self._val(M_TOKENS_PROMPT)
        if cached is None or prefill is None:
            return None
        denom = cached + prefill
        return (cached / denom) if denom > 0 else None
