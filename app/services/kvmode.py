"""KV 容量与模式判定（v0.4 §5.3 / TASK-47 / F14 修复）。

背景（v0.1 的缺陷）：
    ``total_ctx = max(s.n_ctx for s in slots)``
    只对 **unified（-kvu 统一池）** 模式正确。llama-server 有两种 KV 布局：

    | 模式        | 启动参数            | 每槽上报 n_ctx | 真实总容量      |
    |-------------|---------------------|----------------|-----------------|
    | unified     | -kvu / --kv-unified | = 总容量       | n_ctx           |
    | per_slot    | 不加 -kvu（默认）   | = 总容量÷槽数  | 槽数 × n_ctx    |

    非 unified 部署下 ``max()`` 会少算 N 倍，占用率虚高 N 倍，导致正常负载
    就误报 85%/95% KV 告警。

判定链（全部为运行时探测，符合 v0.4 原则 P1/P2/P3）：
    ① unit 的 ``-c`` 值 = 总预算（两种模式都成立，最权威）；
       模式由 ``-kvu`` 直接给出，或用 ``-c`` 与每槽 n_ctx 的算术关系推断：
           -c == 每槽 n_ctx           → unified
           -c == 每槽 n_ctx × 槽数    → per_slot
    ② unit 读不到 → 用 journal 启动日志：
           n_slots = 6, n_ctx_slot = 131072, kv_unified = 'true'
    ③ 两者都拿不到 → 不猜，标记 unknown（原则 P3）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 从 llama-server 启动日志解析 KV 布局
RE_KV_LOG = re.compile(
    r"n_slots\s*=\s*(?P<n_slots>\d+)\s*,\s*n_ctx_slot\s*=\s*(?P<n_ctx_slot>\d+)"
    r"\s*,\s*kv_unified\s*=\s*'(?P<kv_unified>true|false)'",
    re.I,
)


@dataclass
class KvCapacity:
    """KV 总容量判定结果。"""

    total_tokens: int = 0
    mode: str = "unknown"  # unified / per_slot / unknown
    source: str = "none"  # override / unit_kv_flag / unit_ctx_math / journal / slots / none

    @property
    def known(self) -> bool:
        return self.total_tokens > 0 and self.mode != "unknown"


def from_journal_log(text: str) -> KvCapacity | None:
    """从 journal 文本里找 llama-server 的 KV 布局自述（最可靠的一手信息）。"""
    if not text:
        return None
    last: KvCapacity | None = None
    for m in RE_KV_LOG.finditer(text):
        n_slots = int(m.group("n_slots"))
        n_ctx_slot = int(m.group("n_ctx_slot"))
        unified = m.group("kv_unified").lower() == "true"
        total = n_ctx_slot if unified else n_ctx_slot * max(n_slots, 1)
        last = KvCapacity(
            total_tokens=total,
            mode="unified" if unified else "per_slot",
            source="journal",
        )
    return last


def _close(a: int, b: int, tol: float = 0.02) -> bool:
    """整数除法会有舍入（131072/6=21845，×6=131070），故按比例容差比较。"""
    if not b:
        return False
    return abs(a - b) <= max(2, abs(b) * tol)


def decide(
    slot_ctxs: list[int],
    unit_ctx: int = 0,
    kv_unified: bool | None = None,
    journal_text: str = "",
    override: str = "",
) -> KvCapacity:
    """按优先级判定 KV 总容量与模式。

    参数:
        slot_ctxs:   各槽位上报的 ``n_ctx``
        unit_ctx:    unit 的 ``-c`` 值（总预算）
        kv_unified:  unit 是否含 ``-kvu``；``None`` = unit 不可读
        journal_text: journal 文本（可含启动日志）
        override:    配置强制值 ``unified`` / ``per_slot`` / ``""``
    """
    n = len(slot_ctxs)
    per_slot = max(slot_ctxs) if slot_ctxs else 0
    # 各槽 n_ctx 一致时取其一；不一致时保守取最大（异常情况）
    uniform = bool(slot_ctxs) and len(set(slot_ctxs)) == 1

    # ① 配置强制覆盖（最高优先级，运维显式指定）
    if override in ("unified", "per_slot"):
        if override == "unified":
            total = unit_ctx or per_slot
        else:
            total = unit_ctx or (per_slot * n)
        return KvCapacity(total_tokens=total, mode=override, source="override")

    # ② unit 的 -kvu 明确给出模式
    if kv_unified is True:
        total = unit_ctx or per_slot
        return KvCapacity(total_tokens=total, mode="unified", source="unit_kv_flag")
    if kv_unified is False:
        # 没加 -kvu：默认 per_slot；但若 -c 恰好等于每槽 n_ctx，说明实际仍是共享池
        if unit_ctx and per_slot and _close(unit_ctx, per_slot):
            return KvCapacity(total_tokens=unit_ctx, mode="unified", source="unit_ctx_math")
        total = unit_ctx or (per_slot * n)
        return KvCapacity(total_tokens=total, mode="per_slot", source="unit_kv_flag")

    # ③ unit 可读但无 -kvu 信息 → 用 -c 与槽位 n_ctx 的算术关系推断
    if unit_ctx and per_slot:
        if uniform and _close(unit_ctx, per_slot):
            return KvCapacity(total_tokens=unit_ctx, mode="unified", source="unit_ctx_math")
        if uniform and n > 1 and _close(unit_ctx, per_slot * n):
            return KvCapacity(total_tokens=unit_ctx, mode="per_slot", source="unit_ctx_math")
        # -c 与槽位对不上：以 -c 为总预算，模式存疑
        return KvCapacity(total_tokens=unit_ctx, mode="unknown", source="unit_ctx_math")

    # ④ unit 读不到 → journal 启动日志
    j = from_journal_log(journal_text)
    if j is not None and j.total_tokens:
        return j

    # ⑤ 都拿不到 → 不猜（原则 P3）
    return KvCapacity(total_tokens=0, mode="unknown", source="none")


def build_label(slot_count: int, capacity: KvCapacity) -> str:
    """生成 KV 面板说明文案（由后端下发，前端不再硬编码，F15 修复）。"""
    if capacity.total_tokens > 0:
        cap = f"{capacity.total_tokens / 1024:.0f}K"
    else:
        cap = "—"
    if capacity.mode == "unified":
        mode = "-kvu 统一池"
    elif capacity.mode == "per_slot":
        mode = "每槽独立 KV"
    else:
        mode = "KV 模式未知"
    return f"{slot_count} 槽 · 共 {cap} 容量（{mode}）"
