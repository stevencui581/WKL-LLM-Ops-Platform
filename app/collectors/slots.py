"""Collector-A：/slots 槽位采集器（方案 TASK-04）。

这是 KV 池、槽位表、并发数的唯一数据源。
"""

from __future__ import annotations

import time

from ..adapters.llama import LlamaClient
from ..config import Settings
from ..models import KvBlock, SlotInfo
from ..services import kvmode
from ..services.kvmode import KvCapacity
from .base import CollectorState


def slot_state(is_processing: bool, n_prompt_tokens: int) -> str:
    """三态判定（方案 6.2.1「槽位表—状态」）。"""
    if is_processing:
        return "generating"
    if n_prompt_tokens > 0:
        return "cached"
    return "idle"


def parse_slots(payload: list[dict]) -> list[SlotInfo]:
    out: list[SlotInfo] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        n_prompt = int(raw.get("n_prompt_tokens") or 0)
        is_proc = bool(raw.get("is_processing"))
        nt = raw.get("next_token") or []
        n_decoded = 0
        if isinstance(nt, list) and nt and isinstance(nt[0], dict):
            n_decoded = int(nt[0].get("n_decoded") or 0)
        params = raw.get("params") or {}
        out.append(
            SlotInfo(
                id=int(raw.get("id", -1)),
                n_ctx=int(raw.get("n_ctx") or 0),
                is_processing=is_proc,
                id_task=int(raw.get("id_task", -1)),
                n_prompt_tokens=n_prompt,
                n_prompt_tokens_cache=int(raw.get("n_prompt_tokens_cache") or 0),
                n_prompt_tokens_processed=int(raw.get("n_prompt_tokens_processed") or 0),
                n_decoded=n_decoded,
                speculative_types=str(params.get("speculative.types") or ""),
                max_tokens=params.get("max_tokens"),
                state=slot_state(is_proc, n_prompt),
            )
        )
    out.sort(key=lambda s: s.id)
    return out


def build_kv_block(
    slots: list[SlotInfo],
    capacity: KvCapacity,
    quant: tuple[str, str] = ("", ""),
    show_default_quant: bool = True,
) -> KvBlock:
    """KV 池占用率 = Σ 槽位 tokens / 总容量。

    v0.4 §5.3（F14 修复）：分母**不再**取 ``max(n_ctx)`` —— 那只对 unified
    模式正确，非 unified 部署会少算 N 倍。改由 ``kvmode.decide()`` 按
    unit/journal 的运行时探测结果给出总容量与模式。
    """
    used = sum(s.n_prompt_tokens for s in slots)
    total = int(capacity.total_tokens or 0)
    pct = (used / total * 100.0) if total > 0 else None
    k, v = quant
    if k or v:
        qtext, qsource = f"{k or 'f16'}/{v or 'f16'}", "unit"
    elif show_default_quant:
        # v0.4 F16：未配置 -ctk/-ctv 时显示 llama.cpp 的默认值，
        # 但必须**显式标注为「默认」**，不能与探测值混为一谈
        qtext, qsource = "f16（默认）", "default"
    else:
        qtext, qsource = "", "unknown"
    return KvBlock(
        used_tokens=used,
        total_tokens=total,
        pct=pct,
        remaining_tokens=max(total - used, 0) if total > 0 else 0,
        slots=slots,
        capacity_mode=capacity.mode,
        capacity_source=capacity.source,
        label=kvmode.build_label(len(slots), capacity),
        kv_quant=qtext,
        kv_quant_source=qsource,
    )


class SlotsCollector:
    name = "slots"

    def __init__(self, settings: Settings, client: LlamaClient):
        self.s = settings
        self.client = client
        self.state = CollectorState(self.name, settings.stale_after_misses)
        self.slots: list[SlotInfo] = []
        self.total_ctx: int = 0
        self.slots_total: int = 0
        self._last_decoded_sum: int | None = None
        self._last_decoded_ts: float | None = None
        self.slots_delta_tps: float | None = None
        #: v0.5：当前推理框架是否提供 /slots。
        #: ollama / vLLM / SGLang 都没有这个端点 —— 此时**不再反复探测**，
        #: 也不把它算作故障（否则界面上会一直挂"降级"）。
        self.supported: bool = True

    def set_supported(self, supported: bool) -> None:
        if supported == self.supported:
            return
        self.supported = supported
        if supported:
            self.state.reset()
        else:
            # 明确标记为"该框架不提供"，而不是失败
            self.state.ok(0.0)
            self.slots = []
            self.slots_total = 0
            self.total_ctx = 0

    async def collect(self) -> bool:
        if not self.supported:
            return True  # 不支持的接口直接跳过，保持非 stale 状态
        t0 = time.monotonic()
        ok, payload, err = await self.client.slots()
        if not ok:
            self.state.fail(err or "unknown error")
            return False
        slots = parse_slots(payload or [])
        now = time.monotonic()
        decoded_sum = sum(s.n_decoded for s in slots)
        if self._last_decoded_sum is not None and self._last_decoded_ts is not None:
            dt = now - self._last_decoded_ts
            delta = decoded_sum - self._last_decoded_sum
            self.slots_delta_tps = (delta / dt) if dt > 0 and delta >= 0 else None
        self._last_decoded_sum = decoded_sum
        self._last_decoded_ts = now

        self.slots = slots
        self.slots_total = len(slots)
        if slots:
            self.total_ctx = max(s.n_ctx for s in slots)
        self.state.ok((time.monotonic() - t0) * 1000.0)
        return True

    def kv_block(
        self,
        capacity: KvCapacity | None = None,
        quant: tuple[str, str] = ("", ""),
        show_default_quant: bool = True,
    ) -> KvBlock:
        cap = capacity or KvCapacity(total_tokens=self.total_ctx, mode="unknown", source="slots")
        return build_kv_block(self.slots, cap, quant, show_default_quant)

    def processing_count(self) -> int:
        return sum(1 for s in self.slots if s.is_processing)
