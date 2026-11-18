"""自动基线、界面契约与「已有功能不回归」测试（v0.4 TASK-31 / TASK-45）。

包含：
  * 自动基线学习器行为（学习期不采信、冻结、落盘复用、人工覆盖）
  * 前端 DOM 引用安全（删元素不再导致整页停更）
  * 布局契约（R6 2 列 3 行 / R7 底栏 / R8 版号 / R9 两行状态区）
  * v0.1 既有功能不回归
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.services.baseline import BaselineLearner

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


def _settings(tmp_path, **kw) -> Settings:
    kw.setdefault("state_dir", str(tmp_path / "state"))
    kw.setdefault("baseline_persist_path", str(tmp_path / "baseline.json"))
    return Settings(**kw)


# ===========================================================================
# 自动基线（F4）
# ===========================================================================
def test_baseline_waits_for_warmup(tmp_path):
    """学习期内的样本一律丢弃（避免冷启动污染基线）。"""
    s = _settings(tmp_path, baseline_warmup_s=9999, baseline_min_samples=3)
    bl = BaselineLearner(s)
    assert bl.warmed_up is False
    for _ in range(10):
        bl.observe(0.5, 10.0)
    st = bl.state()
    assert st.mtp.samples == 0
    assert st.mtp.state == "learning"
    assert bl.mtp_baseline is None


def test_baseline_freezes_after_enough_samples(tmp_path):
    s = _settings(tmp_path, baseline_warmup_s=0, baseline_min_samples=5)
    bl = BaselineLearner(s)
    for v in (0.80, 0.82, 0.81, 0.83, 0.82):
        bl.observe(v, 60.0)
    st = bl.state()
    assert st.mtp.state == "ready"
    assert st.mtp.source == "learned"
    assert st.mtp.value == pytest.approx(0.82, abs=0.01)
    assert bl.mtp_baseline == pytest.approx(0.82, abs=0.01)


def test_baseline_ignores_invalid_samples(tmp_path):
    s = _settings(tmp_path, baseline_warmup_s=0, baseline_min_samples=2)
    bl = BaselineLearner(s)
    bl.observe(None, None)
    bl.observe(0.0, 0.0)
    bl.observe(-1.0, -5.0)
    assert bl.state().mtp.samples == 0


def test_baseline_persists_and_reloads(tmp_path):
    """基线落盘后重启复用，不重复学习。"""
    s = _settings(tmp_path, baseline_warmup_s=0, baseline_min_samples=3)
    bl = BaselineLearner(s)
    for v in (0.7, 0.8, 0.9):
        bl.observe(v, 50.0)
    assert bl.state().mtp.value is not None
    assert Path(s.baseline_path).exists()

    bl2 = BaselineLearner(s)
    assert bl2.state().mtp.source == "learned"
    assert bl2.mtp_baseline is not None
    assert bl2.mtp_baseline == bl.mtp_baseline


def test_baseline_manual_override(tmp_path):
    s = _settings(tmp_path, baseline_warmup_s=0, mtp_accept_baseline=0.95)
    bl = BaselineLearner(s)
    assert bl.mtp_baseline == 0.95
    assert bl.state().mtp.source == "manual"
    # 人工指定后不再学习
    for v in (0.1, 0.2, 0.3):
        bl.observe(v, 1.0)
    assert bl.mtp_baseline == 0.95


def test_baseline_relearn_ignores_cache(tmp_path):
    s = _settings(tmp_path, baseline_warmup_s=0, baseline_min_samples=2)
    bl = BaselineLearner(s)
    bl.observe(0.5, 10.0)
    bl.observe(0.5, 10.0)
    s2 = _settings(tmp_path, baseline_warmup_s=0, baseline_min_samples=2, baseline_relearn=True)
    bl2 = BaselineLearner(s2)
    assert bl2.state().mtp.state == "learning", "relearn=True 时应忽略落盘基线"


def test_alerts_skip_baseline_rules_while_learning(tmp_path):
    """学习期未就绪 → 不产生 MTP_LOW / DECODE_LOW 告警。"""
    from app.models import KpiBlock, MetricSnapshot
    from app.services.alerts import AlertEngine

    s = _settings(tmp_path, baseline_warmup_s=9999)
    bl = BaselineLearner(s)
    eng = AlertEngine(s, bl)
    snap = MetricSnapshot(ts=time.time())
    snap.kpi = KpiBlock(mtp_accept=0.05, decode_tps=1.0, processing=1)
    alerts = eng.evaluate(snap)
    codes = {a.code for a in alerts}
    assert "MTP_LOW" not in codes
    assert "DECODE_LOW" not in codes


# ===========================================================================
# 前端 DOM 引用安全（隐患 A）
# ===========================================================================
def _html_ids() -> set[str]:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return set(re.findall(r'id="([^"]+)"', html))


def _js_id_refs() -> set[str]:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    return set(re.findall(r"\$\('([^']+)'\)", js)) | set(re.findall(r'set(?:Text|HTML)\("([^"]+)"', js))


def test_no_js_reference_to_missing_element():
    """**关键回归**：JS 不得引用 HTML 中不存在的 id。

    v0.4 R7 删除了底栏的 #platform / #lastRefresh2，若 JS 仍赋值，
    `$('x').textContent = ...` 会抛 TypeError，导致整个 renderOverview 中断、
    页面永久停止刷新。
    """
    ids = _html_ids()
    refs = _js_id_refs()
    missing = sorted(
        r
        for r in refs
        if r not in ids
        and r
        not in {
            "sparkDecode",
            "sparkPrefill",
            "sparkMtp",  # canvas 由绘图函数按需取
        }
    )
    assert not missing, f"JS 引用了不存在的元素 id：{missing}"


def test_removed_elements_are_really_gone():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="platform"' not in html
    assert 'id="lastRefresh2"' not in html
    live = "\n".join(
        ln
        for ln in (STATIC / "app.js").read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith(("//", "*", "/*"))
    )
    assert "lastRefresh2" not in live
    assert "$('platform')" not in live


def test_null_safe_write_helpers_exist():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function setText(" in js
    assert "function setHTML(" in js
    assert "if (el)" in js


# ===========================================================================
# 布局契约
# ===========================================================================
def test_r6_sysgrid_two_columns_three_rows():
    """R6：系统资源 1 列 6 行 → 2 列 3 行。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert 'class="sysgrid"' in html
    assert 'id="sysRows"' not in html, "旧的一列式表格应已移除"
    assert ".sysgrid" in css and "grid-template-columns: 1fr 1fr" in css
    # 6 个指标（v0.4.3：文案走 i18n，改为断言词条键 —— app.js 里不再有中文）
    for key in ("sys.cpu", "sys.mem", "sys.load", "sys.swap", "sys.disk", "sys.net"):
        assert f"t('{key}')" in js, f"系统资源缺少指标 {key}"
    assert "renderSysGrid" in js


def test_r7_footer_only_has_developer_info():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<div class="footer">(.*?)</div>\s*</div>', html, re.S)
    assert m, "找不到 footer"
    body = m.group(1)
    assert "devInfo" in body
    assert "数据每 2 秒刷新" not in body, "底栏刷新频率应已删除"
    assert "最后刷新" not in body, "底栏最后刷新应已删除"


def test_r9_status_area_is_two_rows():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert 'class="meta2col"' in html
    assert ".meta2col" in css
    assert "flex-direction: column" in css
    # 两行各一条
    block = re.search(r'<div class="meta2col">(.*?)</div>', html, re.S).group(1)
    assert block.count('class="meta"') == 2


def test_r1_r2_topbar_chips():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="accelBadge"' in html and 'id="accelText"' in html and 'id="accelTp"' in html
    assert 'id="modelChip"' in html and 'id="modelFull"' in html
    assert "renderTopChips" in js
    assert "tensor_parallel" in js


def test_bandwidth_label_is_dynamic():
    """F1：显存带宽说明不得再是写死的 V100 文案。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "V100 HBM2 峰值" not in html
    assert 'id="bwSub"' in html


# ===========================================================================
# 版本号单一来源（R8）
# ===========================================================================
def test_product_version_single_source():
    s = Settings()
    assert s.product_version == "v0.6"
    assert s.product_name == "WKL-LLM运维平台v0.6"
    assert s.product_name_spaced == "WKL-LLM运维平台 v0.6"


def test_version_not_duplicated_in_static():
    """静态兜底可以存在，但不得出现旧版本号 v0.1。"""
    for name in ("index.html", "app.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert "v0.1" not in text, f"{name} 仍残留旧版号 v0.1"


def test_branding_served_from_backend():
    """品牌信息必须由后端下发，且**随快照**下发（否则 WS 覆盖后失效）。

    v0.6.1：构造逻辑移到 ``app/payload.py``（聚合器与路由共用，见该文件头），
    因此这里同时扫两个文件 —— 破坏了「两条路径同源」即失败。
    """
    src = "\n".join(
        (ROOT / "app" / part).read_text(encoding="utf-8") for part in ("routes/overview.py", "payload.py")
    )
    assert "product_version" in src
    assert "s.product_name" in src


# ===========================================================================
# v0.1 既有功能不回归
# ===========================================================================
def test_existing_endpoints_still_declared():
    routes = ROOT / "app" / "routes"
    text = "".join(p.read_text(encoding="utf-8") for p in routes.rglob("*.py"))
    for path in ("/api/overview", "/api/hardware"):
        assert path in text
    assert "health/live" in text or "/api/health" in text


def test_overview_keeps_v01_fields():
    """契约：/api/overview 原有字段一个不少（向后兼容）。

    v0.6.1：路由不再手工拼字段，改为 ``snap.model_dump()``；
    因此"字段是否还在"由**两处**共同保证 ——
      * ``app/payload.py::OVERVIEW_FIELDS`` 显式声明契约（可被测试直接 import）；
      * 路由必须真的 dump 快照（而不是退回手工拼装）。
    破坏任一条都会失败。
    """
    from app.payload import OVERVIEW_FIELDS

    route = (ROOT / "app" / "routes" / "overview.py").read_text(encoding="utf-8")
    for field in (
        "ts",
        "seq",
        "stale",
        "branding",
        "model",
        "kpi",
        "kv",
        "runtime",
        "system",
        "self",
        "alerts",
        "gpus",
        "thresholds",
        "health",
    ):
        assert field in OVERVIEW_FIELDS, f"/api/overview 契约缺少 v0.1 字段 {field}"
    #: 同源：路由必须 dump 快照，且把 self_info 改名成 self（与 WS 一致）
    assert "snap.model_dump()" in route, "overview 路由必须从快照取全部字段，否则会与 WS 漂移"
    assert 'payload.pop("self_info")' in route, "self_info 必须改名成 self，与 WebSocket 字段名一致"


def test_thresholds_complete_for_frontend():
    """前端用到的每个阈值都必须由后端下发（F5）。"""
    from app.routes.overview import thresholds_of

    class FakeBaselines:
        mtp_baseline = 0.8
        decode_baseline = 60.0

    t = thresholds_of(Settings(), FakeBaselines())
    for key in (
        "gpu_temp_warn_c",
        "gpu_temp_crit_c",
        "vram_warn_pct",
        "vram_crit_pct",
        "vram_color_warn_pct",
        "kv_warn_pct",
        "kv_crit_pct",
        "power_warn_pct",
        "poll_interval_s",
    ):
        assert key in t, f"阈值 {key} 未下发"
    assert "power_warn_w" not in t, "旧的绝对功耗阈值不应再下发"


def test_slot_source_still_unknown_not_fake():
    """v0.1 红线：拿不到来源就显示未知，不得编造。"""
    from app.collectors.slots import parse_slots

    slots = parse_slots([{"id": 0, "n_ctx": 1024, "n_prompt_tokens": 5}])
    assert slots[0].source is None
