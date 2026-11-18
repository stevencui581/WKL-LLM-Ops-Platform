"""v0.4.3 新功能守卫测试（TASK-61）。

* 告警目录双语完整性（14 个代码，zh + en，en 不含中文）
* 告警日志记录器行为（产生/恢复、不重复、落盘、滚动、上限）
* 历史日志档位（1/7/30、非法回退、缓存键含 limit、下载）
* 结构化字段（badge_items / progress_code / reason_codes / bandwidth_known）
* 页面守卫（零图片、无外链、i18n 接入、DOM 引用不悬空、无中文字面量）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.services import alert_catalog
from app.services.alert_log import RAISED, RESOLVED, AlertLog

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


# ===========================================================================
# 1. 告警目录（TASK-49）
# ===========================================================================
def test_catalog_has_fourteen_codes():
    assert len(alert_catalog.ALL_CODES) == 14
    assert len(set(alert_catalog.ALL_CODES)) == 14, "代码不得重复"


def test_catalog_covers_every_alert_code_in_engine():
    """目录必须覆盖告警引擎里实际会产生的每一个代码。

    做法：扫描 ``alerts.py`` 源码里出现的告警代码字符串，逐一要求在目录中。
    新增告警却忘了加目录 → 本测试失败（防止界面上出现裸代码）。
    """
    src = (ROOT / "app" / "services" / "alerts.py").read_text(encoding="utf-8")
    used = set(re.findall(r'"([A-Z][A-Z0-9_]{4,})"', src))
    # 过滤掉非告警代码的常量
    used = {
        c
        for c in used
        if c in alert_catalog.ALL_CODES
        or c.endswith(
            ("_DOWN", "_EXIT", "_CRIT", "_WARN", "_POWER", "_LOW", "_DEFERRED", "_TRUNCATED", "_CANCEL")
        )
    }
    missing = sorted(used - set(alert_catalog.ALL_CODES))
    assert not missing, f"告警引擎产生了目录中不存在的代码：{missing}"


def test_catalog_bilingual_complete():
    for code in alert_catalog.ALL_CODES:
        m = alert_catalog.meta(code)
        assert m.category_zh and m.category_en, code
        assert m.name_zh and m.name_en, code
        # 英文侧不得含中文
        assert not CJK.search(m.category_en), f"{code} 英文类型含中文"
        assert not CJK.search(m.name_en), f"{code} 英文名称含中文"


def test_catalog_english_chinese_differ():
    """英文名不得等于中文名（防止漏翻译）。"""
    for code in alert_catalog.ALL_CODES:
        m = alert_catalog.meta(code)
        assert m.name_zh != m.name_en, f"{code} 中英文名称相同，疑未翻译"


def test_compute_card_term_in_catalog():
    """「算力卡」英文必须是 Compute card（v0.4.3 §5）。"""
    for code in ("GPU_TEMP_WARN", "GPU_TEMP_CRIT", "GPU_POWER"):
        m = alert_catalog.meta(code)
        assert m.category_zh == "算力卡"
        assert m.category_en == "Compute card"
    for code in alert_catalog.ALL_CODES:
        en = alert_catalog.meta(code).category_en.lower()
        assert "accelerator" not in en and "gpu card" not in en


def test_unknown_code_is_not_fabricated():
    m = alert_catalog.meta("SOMETHING_NEW")
    assert m.name_zh == "SOMETHING_NEW" and m.name_en == "SOMETHING_NEW"
    assert m.category_zh == "未分类"


def test_catalog_payload_shape():
    p = alert_catalog.catalog_payload()
    assert set(p["codes"]) == set(alert_catalog.ALL_CODES)
    one = p["codes"]["KV_WARN"]
    assert set(one["category"]) == {"zh", "en"}
    assert set(one["name"]) == {"zh", "en"}


# ===========================================================================
# 2. 告警日志（TASK-50/51）
# ===========================================================================
class _FakeAlert:
    def __init__(self, level="warning", message="m", value=None):
        self.level, self.message, self.value = level, message, value


def _log(tmp_path, **kw) -> AlertLog:
    kw.setdefault("ring_max", 100)
    kw.setdefault("file_max", 1000)
    return AlertLog(path=tmp_path / "alert.jsonl", service="llm-infer.service", **kw)


def test_raised_then_resolved(tmp_path):
    al = _log(tmp_path)
    al.sync({"GPU_TEMP_WARN": _FakeAlert()}, now=1000.0)
    assert al.total == 1 and al.entries[0].event == RAISED
    al.sync({}, now=1100.0)
    assert al.total == 2 and al.entries[1].event == RESOLVED
    assert al.entries[1].duration_s == 100.0


def test_persistent_alert_not_duplicated(tmp_path):
    """同一 code 持续存在期间只记一条 raised（去抖语义）。"""
    al = _log(tmp_path)
    for i in range(20):
        al.sync({"KV_WARN": _FakeAlert()}, now=1000.0 + i)
    assert al.total == 1


def test_multiple_codes_independent(tmp_path):
    al = _log(tmp_path)
    al.sync({"KV_WARN": _FakeAlert(), "MTP_LOW": _FakeAlert()}, now=1.0)
    assert al.total == 2
    al.sync({"KV_WARN": _FakeAlert()}, now=2.0)
    assert al.total == 3
    assert al.entries[-1].code == "MTP_LOW"
    assert al.entries[-1].event == RESOLVED


def test_ring_limit(tmp_path):
    al = _log(tmp_path, ring_max=5)
    for i in range(20):
        al.sync({f"C{i}": _FakeAlert()}, now=float(i))
        al.sync({}, now=float(i) + 0.5)
    assert al.total == 5


def test_persist_and_reload(tmp_path):
    al = _log(tmp_path)
    al.sync({"KV_WARN": _FakeAlert()}, now=1.0)
    al.sync({}, now=2.0)
    al2 = _log(tmp_path)
    n = al2.load()
    assert n == 2 and al2.total == 2
    # 重载后 _since 必须已清理（否则新告警会被误判为"持续中"而不记录）
    al2.sync({"KV_WARN": _FakeAlert()}, now=3.0)
    assert al2.total == 3


def test_load_tolerates_corrupt_lines(tmp_path):
    p = tmp_path / "alert.jsonl"
    p.write_text(
        '{"bad json\n'
        + json.dumps(
            {
                "seq": 1,
                "ts": 1.0,
                "iso": "2026-01-01 00:00:00",
                "code": "KV_WARN",
                "level": "warning",
                "event": "raised",
                "category_zh": "KV 缓存",
                "category_en": "KV cache",
                "name_zh": "KV 池占用偏高",
                "name_en": "KV cache usage high",
                "message": "",
                "value": None,
                "service": "u",
                "duration_s": None,
            }
        )
        + "\n"
        + "not json at all\n",
        encoding="utf-8",
    )
    al = _log(tmp_path)
    assert al.load() == 1


def test_iso_format_is_display_ready(tmp_path):
    al = _log(tmp_path)
    e = al.record("KV_WARN", "warning", RAISED, now=1791005698.0)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", e.iso), e.iso


def test_public_shape_has_bilingual_category_name(tmp_path):
    al = _log(tmp_path)
    al.record("KV_WARN", "warning", RAISED)
    d = al.recent(10)[0].as_public()
    assert d["category"]["zh"] and d["category"]["en"]
    assert d["name"]["zh"] and d["name"]["en"]
    assert "category_zh" not in d, "内部字段不应外泄"


def test_recent_is_newest_first_and_filterable(tmp_path):
    al = _log(tmp_path)
    al.record("KV_WARN", "warning", RAISED, now=1.0)
    al.record("KV_WARN", "info", RESOLVED, now=2.0)
    assert al.recent(10)[0].event == RESOLVED
    assert len(al.recent(10, event=RAISED)) == 1
    assert len(al.recent(10, level="warning")) == 1
    assert len(al.recent(10, q="kv")) == 2


def test_write_failure_does_not_raise(tmp_path):
    """落盘失败（如目录不可写）不得影响采集主流程。"""
    al = AlertLog(path=Path("/proc/nonexistent/x.jsonl"))
    e = al.record("KV_WARN", "warning", RAISED)
    assert e.code == "KV_WARN"
    assert al.stats()["append_failures"] >= 1


# ===========================================================================
# 3. 历史日志档位（TASK-52）
# ===========================================================================
def _settings(tmp_path, **kw) -> Settings:
    kw.setdefault("state_dir", str(tmp_path / "state"))
    return Settings(**kw)


def test_resolve_days(tmp_path):
    from app.collectors.history import LogHistory

    lh = LogHistory(_settings(tmp_path))
    assert lh.resolve_days(None) == 30
    assert [lh.resolve_days(x) for x in (1, 7, 30)] == [1, 7, 30]
    assert lh.resolve_days(5) == 1  # 取不超过请求值的最近档位
    assert lh.resolve_days(20) == 7
    assert lh.resolve_days(999) == 30
    assert lh.resolve_days("abc") == 30  # 非法类型回退默认


def test_build_argv(tmp_path):
    from app.collectors.history import LogHistory

    lh = LogHistory(_settings(tmp_path))
    argv = lh.build_argv(7, 2000)
    assert "-7d" in argv and "-u" in argv
    assert argv[argv.index("-n") + 1] == "2001", "应多取一行用于判断截断"
    assert "short-iso" in argv


def test_cache_key_includes_limit(tmp_path):
    """**回归**：缓存只按 days 键会导致"先查少量、再查全量"命中旧结果。"""
    from app.collectors.history import HistoryResult, LogHistory

    lh = LogHistory(_settings(tmp_path))
    small = HistoryResult(requested_days=30, returned=10)
    big = HistoryResult(requested_days=30, returned=9999)
    import time as _t

    lh._cache[(30, 10)] = (_t.monotonic(), small)
    lh._cache[(30, 15000)] = (_t.monotonic(), big)
    assert lh.cached(30, 10).returned == 10
    assert lh.cached(30, 15000).returned == 9999
    assert lh.cached(30, 2000) is None


def test_cache_entries_bounded(tmp_path):
    """缓存条目必须有上限：单条结果可达上万行，无界增长会吃内存。"""
    from app.collectors.history import HistoryResult, LogHistory

    lh = LogHistory(_settings(tmp_path))
    import time as _t

    for i in range(20):
        lh._cache[(30, 100 + i)] = (_t.monotonic() + i, HistoryResult(returned=1))
    assert len(lh._cache) > 4, "先确认确实堆积了"
    lh._evict()
    assert len(lh._cache) <= 4, f"应被裁剪到 4 条，实际 {len(lh._cache)}"
    # 保留的必须是最新的
    assert (30, 119) in lh._cache


def test_default_limit_covers_max_days():
    """默认拉取上限必须 >= 上限，否则 -n 会从旧端截断（实测踩过的坑）。"""
    s = Settings()
    assert s.log_history_default_limit >= s.log_history_max_lines


def test_days_options_and_default():
    s = Settings()
    assert tuple(s.log_history_days_options) == (1, 7, 30)
    assert s.log_history_default_days == 30


# ===========================================================================
# 4. 结构化字段（TASK-54/55）
# ===========================================================================
def test_progress_code_is_language_neutral():
    from app.services.service_ctl import ServiceController

    assert ServiceController._progress_label("activating", "start", 5.0)[0] == "starting"
    assert ServiceController._progress_label("activating", "start", 60.0)[0] == "model_loading"
    assert ServiceController._progress_label("active", "running", 60.0)[0] == "waiting_ready"
    assert ServiceController._progress_label("failed", "failed", 1.0)[0] == "failed"
    # 枚举值不得含中文
    for active, sub, el in (
        ("activating", "start", 5.0),
        ("active", "running", 1.0),
        ("failed", "failed", 1.0),
    ):
        code, zh = ServiceController._progress_label(active, sub, el)
        assert not CJK.search(code), code
        assert CJK.search(zh), "中文兼容串应保留"


def test_service_status_has_progress_code():
    from app.models import ServiceStatus

    assert ServiceStatus().progress_code == ""


def test_runtime_config_has_badge_items():
    from app.models import RuntimeConfig

    rc = RuntimeConfig()
    assert rc.badge_items == []
    assert rc.badges == [], "旧的兼容字段必须保留"


def test_accel_vendor_has_bandwidth_known():
    from app.models import AccelVendor

    assert AccelVendor().bandwidth_known is None


def test_medata_has_reason_codes(tmp_path):
    """readiness 的结构化原因码。"""
    from app.main import build_container

    c = build_container(_settings(tmp_path))
    ok, codes = c.aggregator.ready_codes()
    assert isinstance(ok, bool)
    for code in codes:
        assert not CJK.search(code), code
        assert code in ("slots_unavailable", "gpu_unavailable", "journal_not_running")


def test_overview_keeps_legacy_and_adds_structured(tmp_path):
    """接口向后兼容：旧字段保留，新字段增加。

    v0.6.1：``health`` 的键集合改为显式契约 ``app/payload.py::HEALTH_FIELDS``
    （原先靠扫 ``overview.py`` 的字符串字面量，重构即误报）；这里断言契约内容，
    比扫源码更强 —— 它同时是 ``health_of()`` 的返回值校验依据。
    """
    from app.payload import HEALTH_FIELDS
    from app.routes.overview import thresholds_of

    assert "reason_codes" in HEALTH_FIELDS
    assert "reasons" in HEALTH_FIELDS
    #: 路由必须仍然 dump 快照（旧字段由快照保证，不能退回手工拼装）
    route = (ROOT / "app" / "routes" / "overview.py").read_text(encoding="utf-8")
    assert "snap.model_dump()" in route
    t = thresholds_of(
        Settings(),
        type("B", (), {"mtp_baseline": None, "decode_baseline": None})(),
    )
    assert "gpu_temp_warn_c" in t


def test_kv_quant_raw_value_has_no_marker():
    """badge_items 里的 kv_quant 必须是**裸值**，标注由前端加（否则会重复）。"""
    from app.collectors.props import PropsCollector
    from app.services.unitinfo import UnitConfig

    class _Client:
        async def get_json(self, *a, **kw):  # pragma: no cover - 不触发
            return None

    c = PropsCollector(Settings(), _Client())
    # readable 是只读属性（由 raw_exec 推导），这里直接给 raw_exec 模拟"读到 unit"
    label, source, raw = c._kv_quant(UnitConfig(raw_exec="ExecStart=/x -kvu"), {})
    assert source == "default"
    assert label == "f16（默认）"
    assert raw == "f16", "裸值不得含「（默认）」"


def test_kv_quant_raw_when_unit_provides_value():
    """显式配置 -ctk/-ctv 时，裸值与显示值一致且来源为 unit。"""
    from app.collectors.props import PropsCollector
    from app.services.unitinfo import UnitConfig

    class _Client:
        async def get_json(self, *a, **kw):  # pragma: no cover
            return None

    c = PropsCollector(Settings(), _Client())
    u = UnitConfig(raw_exec="ExecStart=/x", cache_type_k="q8_0", cache_type_v="q8_0")
    label, source, raw = c._kv_quant(u, {})
    assert source == "unit"
    assert label == raw == "q8_0/q8_0"


# ===========================================================================
# 5. 页面守卫
# ===========================================================================
PAGES = ("index.html", "alerts.html", "logs.html")


@pytest.mark.parametrize("page", PAGES)
def test_page_exists_and_is_selfcontained(page):
    p = STATIC / page
    assert p.exists(), f"缺少页面 {page}"
    html = p.read_text(encoding="utf-8")
    assert "<img" not in html, "零图片红线"
    assert "background-image" not in html
    ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    assert not ext, f"存在外链资源：{ext}"


@pytest.mark.parametrize("page", PAGES)
def test_page_loads_i18n(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    assert "/i18n.js" in html, "每个页面都必须接入 i18n"
    assert "I18N.applyI18n()" in html, "必须在渲染前应用语言"


def test_alerts_page_has_three_required_columns():
    """R10：告警日期时间 / 告警服务类型 / 告警服务名称。"""
    html = (STATIC / "alerts.html").read_text(encoding="utf-8")
    assert 'data-i18n="al.col.time"' in html
    assert 'data-i18n="al.col.category"' in html
    assert 'data-i18n="al.col.name"' in html


def test_logs_page_headline_and_controls():
    """R11：顶部文字随天数；1/7/30 切换；实时；下载。"""
    html = (STATIC / "logs.html").read_text(encoding="utf-8")
    assert 'id="headline"' in html
    assert 'id="dayBtns"' in html
    assert 'id="liveBtn"' in html
    assert 'id="downloadBtn"' in html
    js = (STATIC / "logs.js").read_text(encoding="utf-8")
    assert "t('lg.showing'" in js, "顶部文字必须按档位渲染"
    assert "/api/logs/history/download" in js
    assert "/ws/logs" in js, "实时必须复用现有通道"


def test_index_has_entry_buttons_and_lang_control():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="alertLogBtn"' in html, "告警面板要有告警日志入口（标识1）"
    assert 'id="logHistoryBtn"' in html, "顶栏要有历史服务日志入口（标识3）"
    assert 'id="langCtl"' in html, "顶栏要有语言切换（标识4）"


def test_index_buttons_navigate():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/alerts.html" in js
    assert "/logs.html" in js


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())


@pytest.mark.parametrize("name", ("app.js", "alerts.js", "logs.js"))
def test_no_chinese_literals_in_page_scripts(name):
    """**核心断言**：页面脚本的可执行代码里不得出现中文字符串字面量。

    所有文案必须走 i18n 字典；否则英文模式下会漏出中文。
    """
    src = _strip_js_comments((STATIC / name).read_text(encoding="utf-8"))
    bad = [f"{i + 1}: {ln.strip()}" for i, ln in enumerate(src.splitlines()) if CJK.search(ln)]
    assert not bad, f"{name} 的可执行代码里仍有中文：\n" + "\n".join(bad)


def test_js_dom_refs_not_dangling():
    """页面脚本引用的元素 id 必须存在于对应 HTML 中。

    v0.4 曾因 `$('x').textContent = ...` 引用已删除元素而整页停更。
    """
    pairs = {
        "app.js": "index.html",
        "alerts.js": "alerts.html",
        "logs.js": "logs.html",
    }
    for js_name, html_name in pairs.items():
        ids = set(re.findall(r'id="([^"]+)"', (STATIC / html_name).read_text(encoding="utf-8")))
        js = (STATIC / js_name).read_text(encoding="utf-8")
        refs = set(re.findall(r"\$\('([^']+)'\)", js))
        missing = sorted(
            r for r in refs if r not in ids and r not in {"sparkDecode", "sparkPrefill", "sparkMtp"}
        )
        assert not missing, f"{js_name} 引用了 {html_name} 中不存在的 id：{missing}"


def test_newlines_indicator_present():
    """实时新行指示器（用户向下滚时不跳动，改为提示条数）。"""
    js = (STATIC / "logs.js").read_text(encoding="utf-8")
    assert "unseen" in js and "lg.new_lines" in js
    html = (STATIC / "logs.html").read_text(encoding="utf-8")
    assert 'id="newLines"' in html


def test_live_cleanup_on_close():
    """关闭实时必须主动断开 WebSocket（防订阅泄漏）。"""
    js = (STATIC / "logs.js").read_text(encoding="utf-8")
    assert "function stopLive" in js
    assert "ws.close()" in js
    assert "beforeunload" in js


def test_live_ignores_backfill():
    """实时必须忽略首帧 backfill（历史基线由 REST 提供，否则行会重复）。"""
    js = (STATIC / "logs.js").read_text(encoding="utf-8")
    assert "msg.type === 'backfill'" in js
    idx = js.index("msg.type === 'backfill'")
    seg = js[idx : idx + 120]
    assert "return" in seg, "backfill 分支必须直接 return，不得渲染"


def test_cancel_event_counted_despite_no_other_fields():
    """**回归**：取消行只有 cancel 一个特征，历史上被 `if not fields: return` 吞掉。

    llama.cpp 的取消行形如
    ``206.40.125.385 W srv stop: cancel task, id_task = 47734``，
    它不含 acceptance/eval/release 等任何字段，因此 ``parse_all`` 返回空字典。
    若取消判断写在空字典早退之后，``cancel_events`` 永远为 0，
    ``CLIENT_CANCEL`` 告警就永远不会触发（自 v0.1 起的真实缺陷）。
    """
    from app.services.log_stats import LogStats

    st = LogStats()
    st.update("206.40.125.385 W srv          stop: cancel task, id_task = 47734", 1791000000.0)
    assert st.cancel_events == 1, "取消事件必须被计数（即使该行没有其它字段）"

    st.update("206.41.131.377 W srv          stop: cancel task, id_task = 47735", 1791000001.0)
    assert st.cancel_events == 2

    # 普通行不应误计数
    st.update("0.06.106.069 I srv  llama_server: model loaded", 1791000002.0)
    assert st.cancel_events == 2
    assert st.model_loaded_ts == 1791000002.0


def test_event_alert_auto_resolves(tmp_path):
    """**回归**：事件型告警必须有恢复，否则界面永久挂着、日志只有 raised。

    历史行为：``_event_alerts`` 从未被清除，一次取消就让 CLIENT_CANCEL
    永久处于 active 状态。

    注意：``evaluate()`` 内部用真实 ``time.time()`` 判断 TTL，
    因此这里必须用**相对于当前时刻**的时间戳，不能用假时间。
    """
    import time as _t

    from app.models import MetricSnapshot
    from app.services.alert_log import AlertLog
    from app.services.alerts import AlertEngine

    s = Settings(state_dir=str(tmp_path), event_alert_ttl_s=10.0)
    al = AlertLog(path=tmp_path / "a.jsonl", service="llm-infer.service")
    eng = AlertEngine(s, None, al)

    # 刚发生 → 应产生告警
    eng.note_cancel()
    a1 = eng.evaluate(MetricSnapshot(ts=_t.time()))
    assert any(a.code == "CLIENT_CANCEL" for a in a1), "事件后应产生告警"

    # 仍在窗口内 → 保持
    eng._event_since["CLIENT_CANCEL"] = _t.time() - 3.0
    assert any(a.code == "CLIENT_CANCEL" for a in eng.evaluate(MetricSnapshot(ts=_t.time())))

    # 超过 TTL → 自动恢复
    eng._event_since["CLIENT_CANCEL"] = _t.time() - 11.0
    a2 = eng.evaluate(MetricSnapshot(ts=_t.time()))
    assert not any(a.code == "CLIENT_CANCEL" for a in a2), "超过 TTL 应自动恢复"
    assert "CLIENT_CANCEL" not in eng._event_alerts, "应被清除，不再重复触发"

    events = [e.event for e in al.entries if e.code == "CLIENT_CANCEL"]
    assert events == ["raised", "resolved"], f"日志应含产生与恢复：{events}"


def test_event_alert_ttl_zero_keeps_active(tmp_path):
    """ttl=0 表示不自动恢复（保留旧行为，供运维显式选择）。"""
    import time as _t

    from app.models import MetricSnapshot
    from app.services.alerts import AlertEngine

    s = Settings(state_dir=str(tmp_path), event_alert_ttl_s=0.0)
    eng = AlertEngine(s, None, None)
    eng.note_cancel()
    eng._event_since["CLIENT_CANCEL"] = _t.time() - 99999.0
    assert any(a.code == "CLIENT_CANCEL" for a in eng.evaluate(MetricSnapshot(ts=_t.time())))


def test_event_alert_refreshes_window(tmp_path):
    """重复发生的事件应刷新窗口（持续发生则保持告警）。"""
    from app.services.alerts import AlertEngine

    s = Settings(state_dir=str(tmp_path), event_alert_ttl_s=10.0)
    eng = AlertEngine(s, None, None)
    eng.note_cancel()
    first = eng._event_since["CLIENT_CANCEL"]
    eng.note_cancel()
    assert eng._event_since["CLIENT_CANCEL"] >= first, "应刷新为最新时刻"


def test_cancel_alert_reaches_alert_log(tmp_path):
    """取消事件 → 告警引擎 → 告警日志，全链路可记录。"""
    from app.models import MetricSnapshot
    from app.services.alert_log import AlertLog
    from app.services.alerts import AlertEngine

    al = AlertLog(path=tmp_path / "a.jsonl", service="llm-infer.service")
    eng = AlertEngine(Settings(state_dir=str(tmp_path)), None, al)
    eng.note_cancel()
    alerts = eng.evaluate(MetricSnapshot(ts=1791000000.0))
    assert any(a.code == "CLIENT_CANCEL" for a in alerts)
    assert al.total == 1
    e = al.recent(5)[0].as_public()
    assert e["code"] == "CLIENT_CANCEL"
    assert e["category"]["zh"] and e["category"]["en"]
    assert len(e["iso"]) == 19


def test_static_has_no_old_version():
    """静态资源不得残留旧版号**占位**。

    只检查可执行/可见内容：注释里的历史标注（如
    ``<!-- 标识4（v0.4.3 R12）：中/英切换 -->``）是**说明**，不是版号残留，
    因此必须先剥离 HTML 与 JS 注释再判断 —— 否则守卫会因为注释而误报。
    """
    for name in ("index.html", "alerts.html", "logs.html", "app.js"):
        raw = (STATIC / name).read_text(encoding="utf-8")
        text = _strip_js_comments(raw)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        for old in ("v0.4.1", "v0.4.2", "v0.4.3"):
            assert old not in text, f"{name} 残留旧版号 {old}"


def test_current_version_present_in_static():
    """当前版号必须出现在静态兜底里（接口未返回时的首屏占位）。"""
    from app.config import Settings

    ver = Settings().product_version
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert f'class="ver">{ver}<' in html, f"index.html 应包含 {ver} 占位"


def test_page_scripts_have_no_version_literal():
    """页面脚本里**不得出现任何版本号字面量**（v0.4 R8 单一事实源）。

    v0.4.4 踩过的坑：`app.js` 里留了 `|| 'v0.4.3'` 兜底，升版时漏改，
    导致顶栏可能显示旧版号。现在版号只从后端 `branding.product_version` 取，
    前端一个字面量都不留 —— 升版只需改 `config.py` 一处。
    """
    for name in ("app.js", "alerts.js", "logs.js", "i18n.js"):
        code = _strip_js_comments((STATIC / name).read_text(encoding="utf-8"))
        found = re.findall(r"v\d+\.\d+(?:\.\d+)?", code)
        assert not found, f"{name} 含版本号字面量 {found}，应从后端取"
