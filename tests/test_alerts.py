"""告警引擎测试（方案 TASK-20 验收标准）。"""

from __future__ import annotations

import time

from app.models import GpuInfo, KpiBlock, KvBlock, MetricSnapshot, SlotInfo
from app.services.alerts import AlertEngine, _Debounce


def snap(**kw) -> MetricSnapshot:
    s = MetricSnapshot(seq=1, ts=time.time(), stale={"slots": False, "gpu": False})
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_debounce_requires_sustain():
    d = _Debounce(10.0)
    t0 = 1000.0
    assert d.update(True, t0) is False  # 刚触发，未满 10 秒
    assert d.update(True, t0 + 5) is False
    assert d.update(True, t0 + 10) is True  # 持续满 10 秒
    assert d.update(False, t0 + 11) is False  # 条件消失立即复位
    assert d.update(True, t0 + 12) is False  # 重新计时


def test_service_down_after_two_ticks(settings):
    e = AlertEngine(settings)
    s = MetricSnapshot(seq=1, ts=time.time(), stale={"slots": True})
    a1 = e.evaluate(s)
    assert not [x for x in a1 if x.code == "SERVICE_DOWN"]
    a2 = e.evaluate(s)
    assert [x for x in a2 if x.code == "SERVICE_DOWN"]


def test_gpu_temp_critical_immediate(settings):
    e = AlertEngine(settings)
    s = snap(gpus=[GpuInfo(index=0, temp_c=90.0)])
    a = e.evaluate(s)
    assert any(x.code == "GPU_TEMP_CRIT" and x.level == "critical" for x in a)


def test_gpu_temp_warn_needs_sustain(settings):
    settings.gpu_temp_sustain_s = 0.0  # 测试中缩短，逻辑不变
    e = AlertEngine(settings)
    s = snap(gpus=[GpuInfo(index=0, temp_c=85.0)])
    a = e.evaluate(s)
    assert any(x.code == "GPU_TEMP_WARN" for x in a)


def test_vram_levels(settings):
    e = AlertEngine(settings)
    warn = e.evaluate(snap(kpi=KpiBlock(vram_used_mib=15000, vram_total_mib=16384)))
    assert any(x.code == "VRAM_WARN" for x in warn)
    e2 = AlertEngine(settings)
    crit = e2.evaluate(snap(kpi=KpiBlock(vram_used_mib=16000, vram_total_mib=16384)))
    assert any(x.code == "VRAM_CRIT" for x in crit)


def test_kv_levels(settings):
    settings.kv_sustain_s = 0.0
    e = AlertEngine(settings)
    a = e.evaluate(snap(kv=KvBlock(used_tokens=120000, total_tokens=131072, pct=91.5)))
    assert any(x.code == "KV_WARN" for x in a)

    e2 = AlertEngine(settings)
    a2 = e2.evaluate(snap(kv=KvBlock(used_tokens=128000, total_tokens=131072, pct=97.7)))
    assert any(x.code == "KV_CRIT" for x in a2)


def _engine_with_baseline(settings, mtp=None, decode=None):
    """v0.4 F4：基线不再写死在配置里，测试通过自动学习器注入基线。"""
    from app.services.baseline import BaselineLearner

    settings.baseline_warmup_s = 0
    settings.baseline_min_samples = 2
    settings.mtp_accept_baseline = mtp
    settings.decode_baseline_tps = decode
    bl = BaselineLearner(settings)
    if mtp is None and decode is None:
        pass
    return AlertEngine(settings, bl)


def test_mtp_low_uses_learned_baseline_not_case_value(settings):
    """v0.4 F4：基线来自自动学习（本机 81.8%），案例值 50% 不可照搬。"""
    settings.mtp_sustain_s = 0.0
    e = _engine_with_baseline(settings, mtp=0.818)
    # 60% 低于基线*0.8=65.4% → 应告警；若照搬案例 50% 就不会告警
    a = e.evaluate(snap(kpi=KpiBlock(mtp_accept=0.60)))
    assert any(x.code == "MTP_LOW" for x in a)
    e2 = _engine_with_baseline(settings, mtp=0.818)
    b = e2.evaluate(snap(kpi=KpiBlock(mtp_accept=0.818)))
    assert not any(x.code == "MTP_LOW" for x in b)


def test_mtp_low_silent_when_baseline_still_learning(settings):
    """学习期未就绪 → 不产生基线类告警（避免刚部署就误报）。"""
    from app.services.baseline import BaselineLearner

    settings.baseline_warmup_s = 9999
    settings.mtp_accept_baseline = None
    bl = BaselineLearner(settings)
    e = AlertEngine(settings, bl)
    a = e.evaluate(snap(kpi=KpiBlock(mtp_accept=0.05, decode_tps=0.5, processing=1)))
    assert not any(x.code == "MTP_LOW" for x in a)
    assert not any(x.code == "DECODE_LOW" for x in a)


def test_decode_low_only_when_processing(settings):
    settings.decode_sustain_s = 0.0
    e = _engine_with_baseline(settings, decode=68.0)
    idle = e.evaluate(snap(kpi=KpiBlock(decode_tps=5.0, processing=0)))
    assert not any(x.code == "DECODE_LOW" for x in idle)
    e2 = _engine_with_baseline(settings, decode=68.0)
    busy = e2.evaluate(snap(kpi=KpiBlock(decode_tps=5.0, processing=1)))
    assert any(x.code == "DECODE_LOW" for x in busy)


def test_deferred_requires_sustain(settings):
    settings.deferred_sustain_s = 0.0
    e = AlertEngine(settings)
    a = e.evaluate(snap(kpi=KpiBlock(deferred=3)))
    assert any(x.code == "REQ_DEFERRED" for x in a)


def test_event_alerts_exit_truncate_cancel(settings):
    e = AlertEngine(settings)
    e.note_exit(0)
    e.note_truncated()
    e.note_cancel()
    a = e.evaluate(snap())
    codes = {x.code for x in a}
    assert {"PROC_EXIT", "CTX_TRUNCATED", "CLIENT_CANCEL"} <= codes
    levels = {x.code: x.level for x in a}
    assert levels["PROC_EXIT"] == "critical"
    assert levels["CTX_TRUNCATED"] == "warning"
    assert levels["CLIENT_CANCEL"] == "info"


def test_resolved_event_emitted_on_clear(settings):
    e = AlertEngine(settings)
    e.note_cancel()
    e.evaluate(snap())
    e.clear_event("CLIENT_CANCEL")
    e.evaluate(snap())
    assert any(x.code == "CLIENT_CANCEL" for x in e.resolved_events)


def test_alerts_sorted_by_severity(settings):
    e = AlertEngine(settings)
    e.note_exit(0)
    s = snap(gpus=[GpuInfo(index=0, temp_c=90.0)], kpi=KpiBlock(vram_used_mib=16000, vram_total_mib=16384))
    a = e.evaluate(s)
    levels = [x.level for x in a]
    assert levels == sorted(levels, key=lambda lv: {"critical": 0, "warning": 1, "info": 2}[lv])


def test_no_alert_on_healthy_snapshot(settings):
    e = AlertEngine(settings)
    s = snap(
        gpus=[
            GpuInfo(index=0, temp_c=31, power_w=39.6, mem_used_mib=14593, mem_total_mib=16384),
            GpuInfo(index=1, temp_c=30, power_w=36.4, mem_used_mib=14593, mem_total_mib=16384),
        ],
        kpi=KpiBlock(
            vram_used_mib=29186, vram_total_mib=32768, mtp_accept=0.818, decode_tps=68.2, processing=0
        ),
        kv=KvBlock(
            used_tokens=56414, total_tokens=131072, pct=43.04, slots=[SlotInfo(id=2, n_prompt_tokens=56414)]
        ),
    )
    assert e.evaluate(s) == []
