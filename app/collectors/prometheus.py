"""Collector-E：/metrics Prometheus 采集器（方案 TASK-09）。

关键行为：
  * ``/props`` 的 ``endpoint_metrics=false`` 时**不发起任何请求**（避免每 2 秒打一次无效请求）；
  * 若误发起并收到 501，则识别 ``not_supported_error`` 并**永久降级**；
  * 命名坑：生成计数是 ``tokens_predicted_total``，而生成速率是 ``predicted_tokens_seconds``；
  * 缓存命中率 = cached / (cached + prefill)，不是 cached / prefill。
"""

from __future__ import annotations

import time

from ..adapters.llama import LlamaClient
from ..config import Settings
from .base import CollectorState, to_num

WANTED = (
    "llamacpp:requests_processing",
    "llamacpp:requests_deferred",
    "llamacpp:tokens_predicted_total",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:prompt_tokens_total",
    "llamacpp:prompt_seconds_total",
    "llamacpp:prompt_tokens_cached_total",
    "llamacpp:spec_decode_num_drafts_total",
    "llamacpp:spec_decode_num_draft_tokens_total",
    "llamacpp:spec_decode_num_accepted_tokens_total",
)


def parse_prometheus(text: str) -> dict[str, float]:
    """解析 Prometheus 文本格式，只保留我们关心的序列（均无标签）。"""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition(" ")
        name = name.strip()
        if name not in WANTED:
            continue
        v = to_num(value.strip())
        if v is not None:
            out[name] = v
    return out


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

    def mark_disabled(self, reason: str) -> None:
        self.available = False
        self.disabled_reason = reason

    def set_endpoint_enabled(self, enabled: bool) -> None:
        """跟随 /props 的 endpoint_metrics 同步状态。

        关键点：如果之前因为「服务端未启用」而永久降级，那么运维在服务端
        加上 --metrics 并重启后，控制台必须**自己恢复**，不需要重启控制台。
        实测踩过这个坑：不加这段，启用 --metrics 后界面一直显示未启用。
        """
        if not enabled:
            if self.available is not False:
                self.mark_disabled("服务端未启用 --metrics（/props endpoint_metrics=false）")
            return
        if self.available is False:
            # 重新变为未知，下一次 collect() 会真正去探测
            self.available = None
            self.disabled_reason = None

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
        values = parse_prometheus(text)
        if not values:
            self.state.fail("metrics endpoint returned no known series")
            return False
        self.values = values
        self.available = True
        self._last_ok_mono = time.monotonic()
        self.state.ok((time.monotonic() - t0) * 1000.0)
        return True

    # ---- 派生量（方案 6.2.1）----
    def tokens_predicted_total(self) -> float | None:
        return self.values.get("llamacpp:tokens_predicted_total")

    def requests_deferred(self) -> float | None:
        v = self.values.get("llamacpp:requests_deferred")
        return None if v is None else v

    def decode_tps(self) -> float | None:
        """必须用计数器推导；``predicted_tokens_seconds`` 空闲时为 0，不可直接告警。"""
        tok = self.values.get("llamacpp:tokens_predicted_total")
        sec = self.values.get("llamacpp:tokens_predicted_seconds_total")
        if tok is None or sec is None or sec <= 0:
            return None
        return tok / sec

    def mtp_accept(self) -> float | None:
        acc = self.values.get("llamacpp:spec_decode_num_accepted_tokens_total")
        gen = self.values.get("llamacpp:spec_decode_num_draft_tokens_total")
        if acc is None or gen is None or gen <= 0:
            return None
        return acc / gen

    def cache_hit_ratio(self) -> float | None:
        cached = self.values.get("llamacpp:prompt_tokens_cached_total")
        prefill = self.values.get("llamacpp:prompt_tokens_total")
        if cached is None or prefill is None:
            return None
        denom = cached + prefill
        return (cached / denom) if denom > 0 else None
