"""KV 容量模式判定测试（v0.4 §5.3 / TASK-47 / F14 修复）。

**这是本次升级最关键的单点测试**：v0.1 的 ``max(n_ctx)`` 只对 unified 模式正确，
非 unified 部署会把容量少算 N 倍，导致正常负载就误报 85%/95% KV 告警。
"""

from __future__ import annotations

from app.services import kvmode
from app.services.kvmode import KvCapacity, build_label, decide, from_journal_log

#: 目标 的启动日志实测片段（夹具：来自真实机器，仅用于测试）
JOURNAL_REAL = (
    "2026-10-01T21:14:58 I srv  load_model: initializing, n_slots = 6, "
    "n_ctx_slot = 131072, kv_unified = 'true'"
)
JOURNAL_PER_SLOT = (
    "2026-10-01T21:14:58 I srv  load_model: initializing, n_slots = 6, "
    "n_ctx_slot = 21845, kv_unified = 'false'"
)


# ---------------------------------------------------------------- unified
def test_unified_from_kv_flag():
    """unit 明确带 -kvu —— 容量 = -c 总预算。"""
    cap = decide(slot_ctxs=[131072] * 6, unit_ctx=131072, kv_unified=True)
    assert cap.total_tokens == 131072
    assert cap.mode == "unified"
    assert cap.source == "unit_kv_flag"


# ---------------------------------------------------------------- per_slot
def test_per_slot_from_kv_flag():
    """unit 明确不带 -kvu —— 容量 = 总预算（Σ 每槽）。"""
    cap = decide(slot_ctxs=[21845] * 6, unit_ctx=131072, kv_unified=False)
    assert cap.total_tokens == 131072
    assert cap.mode == "per_slot"
    assert cap.source == "unit_kv_flag"


def test_per_slot_uses_slot_sum_when_unit_ctx_missing():
    cap = decide(slot_ctxs=[21845] * 6, unit_ctx=0, kv_unified=False)
    assert cap.total_tokens == 21845 * 6
    assert cap.mode == "per_slot"


# ---------------------------------------------------------------- 算术推断
def test_unified_inferred_by_ctx_math():
    """unit 可读但没有 -kvu 信息：-c == 每槽 n_ctx → unified。"""
    cap = decide(slot_ctxs=[131072] * 6, unit_ctx=131072, kv_unified=None)
    assert cap.total_tokens == 131072
    assert cap.mode == "unified"
    assert cap.source == "unit_ctx_math"


def test_per_slot_inferred_by_ctx_math():
    """-c == 每槽 n_ctx × 槽数 → per_slot，且容量取 -c（不是单槽）。"""
    cap = decide(slot_ctxs=[21845] * 6, unit_ctx=131072, kv_unified=None)
    assert cap.total_tokens == 131072
    assert cap.mode == "per_slot"
    assert cap.source == "unit_ctx_math"


def test_six_fold_error_is_fixed():
    """回归：v0.1 的 max() 只给出单槽 21845，正确值是**总预算 131072**（差 6 倍）。"""
    slots = [21845] * 6
    v01_wrong = max(slots)
    assert v01_wrong == 21845
    cap = decide(slot_ctxs=slots, unit_ctx=131072, kv_unified=False)
    assert cap.total_tokens == 131072, "必须以 unit 的 -c 为总预算"
    assert cap.total_tokens > v01_wrong * 5


# ---------------------------------------------------------------- journal 兜底
def test_journal_unified():
    cap = from_journal_log(JOURNAL_REAL)
    assert cap is not None
    assert cap.mode == "unified"
    assert cap.total_tokens == 131072


def test_journal_per_slot():
    cap = from_journal_log(JOURNAL_PER_SLOT)
    assert cap is not None
    assert cap.mode == "per_slot"
    assert cap.total_tokens == 21845 * 6


def test_journal_used_when_unit_unreadable():
    cap = decide(slot_ctxs=[21845] * 6, unit_ctx=0, kv_unified=None, journal_text=JOURNAL_PER_SLOT)
    # 21845 × 6 = 131070（llama.cpp 整数除分配每槽上下文，有 2 的舍入）
    assert cap.total_tokens == 21845 * 6
    assert cap.source == "journal"


def test_journal_garbage_is_ignored():
    assert from_journal_log("nothing here") is None
    assert from_journal_log("") is None


# ---------------------------------------------------------------- 不猜
def test_unknown_when_nothing_available():
    """unit 与 journal 都拿不到 → 不猜（原则 P3）。"""
    cap = decide(slot_ctxs=[], unit_ctx=0, kv_unified=None, journal_text="")
    assert cap.total_tokens == 0
    assert cap.mode == "unknown"
    assert cap.source == "none"
    assert cap.known is False


def test_override_wins():
    cap = decide(slot_ctxs=[21845] * 6, unit_ctx=131072, kv_unified=True, override="per_slot")
    assert cap.mode == "per_slot"
    assert cap.source == "override"
    assert cap.total_tokens == 131072


# ---------------------------------------------------------------- 文案
def test_label_reflects_mode():
    uni = KvCapacity(total_tokens=131072, mode="unified", source="unit_kv_flag")
    per = KvCapacity(total_tokens=131072, mode="per_slot", source="unit_kv_flag")
    unk = KvCapacity(total_tokens=0, mode="unknown", source="none")
    assert "统一池" in build_label(6, uni)
    assert "每槽独立" in build_label(6, per)
    assert "未知" in build_label(6, unk)
    assert "128K" in build_label(6, uni)
    assert "—" in build_label(6, unk)


def test_kv_block_from_collector_uses_capacity():
    """build_kv_block 必须用传入的容量，而不是槽位里的 max(n_ctx)。"""
    from app.collectors.slots import build_kv_block, parse_slots

    payload = [{"id": i, "n_ctx": 21845, "n_prompt_tokens": 100} for i in range(6)]
    slots = parse_slots(payload)
    cap = KvCapacity(total_tokens=131072, mode="per_slot", source="unit_kv_flag")
    kv = build_kv_block(slots, cap)
    assert kv.total_tokens == 131072
    assert kv.used_tokens == 600
    assert kv.pct == 600 / 131072 * 100
    assert kv.capacity_mode == "per_slot"
    assert "每槽独立" in kv.label


def test_kv_quant_source_marking():
    """KV 量化必须带来源标记（F16）：unit / default / unknown。"""
    from app.collectors.slots import build_kv_block, parse_slots

    slots = parse_slots([{"id": 0, "n_ctx": 1024, "n_prompt_tokens": 0}])
    cap = KvCapacity(total_tokens=1024, mode="unified", source="unit_kv_flag")

    kv_unit = build_kv_block(slots, cap, quant=("q8_0", "q8_0"), show_default_quant=True)
    assert kv_unit.kv_quant == "q8_0/q8_0"
    assert kv_unit.kv_quant_source == "unit"

    kv_def = build_kv_block(slots, cap, quant=("", ""), show_default_quant=True)
    assert kv_def.kv_quant == "f16（默认）", "默认值必须显式标注「默认」（F16）"
    assert kv_def.kv_quant_source == "default"

    kv_unk = build_kv_block(slots, cap, quant=("", ""), show_default_quant=False)
    assert kv_def.kv_quant != kv_unk.kv_quant or kv_unk.kv_quant_source == "unknown"
    assert kv_unk.kv_quant_source == "unknown"


def test_kvmode_module_has_no_253_literals():
    """kvmode 是通用逻辑，不得含特定机器字面量。"""
    import inspect

    src = inspect.getsource(kvmode)
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    for token in ("llmops", "/home/", "172.16"):
        assert token not in code
