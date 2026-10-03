"""缺陷回归台账（v0.4.4 / TASK-63）。

把 v0.4.3 修复的 **8 个缺陷**固化为可重复执行的守卫，一项一条，
每条都写明**原始症状**与**判据**，防止将来重构时无声复发。

**本文件最重要的一条经验**：
    源码扫描必须先**剥离注释与文档字符串**再判断。
    本台账的第一版审计脚本就是因为 `find("if not fields:")` 命中了
    注释里的示例文字，把**已经修好的** D1 误判为"未修复"。
    这与 D5（UTF-8 BOM 让源码扫描失效）是同一类失败模式 ——
    **守卫本身不可靠，比没有守卫更危险**（会给出虚假的安全感）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TESTS = ROOT / "tests"
TOOLS = ROOT / "tools"


# ---------------------------------------------------------------- 扫描助手
def _strip_py(src: str) -> str:
    """剥离 Python 注释与三引号块，只留可执行代码。

    先去 BOM：否则 ``startswith('\"\"\"')`` 判不出首行文档字符串。
    """
    src = src.lstrip("\ufeff")
    out: list[str] = []
    in_doc = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            marks = s.count('"""') + s.count("'''")
            if marks == 1:
                in_doc = not in_doc
            continue
        if in_doc:
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def _code(rel: str) -> str:
    return _strip_py((ROOT / rel).read_text(encoding="utf-8"))


def _all_test_source() -> str:
    return "".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))


# ===========================================================================
# D1 —— CLIENT_CANCEL 告警从未生效（v0.1 潜伏）
# ===========================================================================
def test_d1_cancel_detection_precedes_early_return():
    """原始症状：取消一次生成后，告警日志里永远没有 CLIENT_CANCEL 记录。

    根因：取消检测写在 ``if not fields: return`` 之后，而取消行
    （``stop: cancel task, id_task = 47734``）不含任何可识别字段，
    ``parse_all`` 返回空字典 → 提前返回 → ``cancel_events`` 恒为 0。

    判据：**代码中**取消检测的行号必须小于空字典早退的行号。
    """
    code = _code("app/services/log_stats.py")
    lines = code.splitlines()

    def first_line(needle: str) -> int:
        for i, ln in enumerate(lines):
            if needle in ln:
                return i
        return -1

    cancel = first_line('"cancel task" in text')
    early = first_line("if not fields:")
    assert cancel >= 0, "找不到取消检测代码"
    assert early >= 0, "找不到空字典早退代码"
    assert cancel < early, (
        f"取消检测（第 {cancel + 1} 行）必须在空字典早退（第 {early + 1} 行）之前，"
        "否则 CLIENT_CANCEL 永不触发"
    )


def test_d1_cancel_counted_with_real_log_line():
    """行为判据：真实取消日志行必须让计数器 +1。"""
    from app.services.log_stats import LogStats

    st = LogStats()
    st.update("206.40.125.385 W srv          stop: cancel task, id_task = 47734", 1.0)
    assert st.cancel_events == 1
    st.update("0.06.106.069 I srv  llama_server: model loaded", 2.0)
    assert st.cancel_events == 1, "普通行不得误计数"


def test_d1_guard_exists():
    assert "test_cancel_event_counted_despite_no_other_fields" in _all_test_source()


# ===========================================================================
# D2 —— 事件型告警永不恢复
# ===========================================================================
def test_d2_ttl_configured_and_enforced():
    """原始症状：一次取消后，「客户端取消生成」告警永久挂在界面上。

    根因：``_event_alerts`` 从未被清除（``clear_event`` 无调用方）。
    """
    from app.config import Settings

    assert Settings().event_alert_ttl_s > 0, "必须有自动恢复窗口"
    code = _code("app/services/alerts.py")
    assert "clear_event(code)" in code, "evaluate 里必须真的调用 clear_event 清除"
    assert "event_alert_ttl_s" in code, "必须读配置的 TTL"


def test_d2_note_helpers_refresh_window():
    """持续发生的事件应刷新窗口（赋值而非 setdefault）。"""
    code = _code("app/services/alerts.py")
    seg = code[code.index("def note_exit") : code.index("def clear_event")]
    assert "setdefault" not in seg, "note_* 必须刷新时间窗口，不能用 setdefault"
    assert seg.count("_event_since[") >= 3, "三个事件型告警都要刷新窗口"


def test_d2_guard_exists():
    src = _all_test_source()
    assert "test_event_alert_auto_resolves" in src
    assert "test_event_alert_ttl_zero_keeps_active" in src


# ===========================================================================
# D3 —— 历史日志「选 30 天却只覆盖 1 天」
# ===========================================================================
def test_d3_cache_key_includes_limit():
    """原始症状：请求 30 天只返回 2000 行（实际覆盖 1 天）。

    根因之一：缓存只按 ``days`` 作键。
    """
    from app.collectors.history import HistoryResult, LogHistory
    from app.config import Settings

    lh = LogHistory(Settings())
    assert isinstance(lh._cache, dict)
    # 类型注解与实现都必须是 (days, limit) 二元键
    code = _code("app/collectors/history.py")
    assert "(days, limit)" in code or "(d, lim)" in code, "缓存键必须含 limit"
    lh._cache[(30, 100)] = (0.0, HistoryResult(returned=1))
    lh._cache[(30, 999)] = (0.0, HistoryResult(returned=2))
    assert len(lh._cache) == 2, "不同 limit 必须是不同缓存项"


def test_d3_route_uses_config_default_limit():
    """原始症状之二：路由把 ``limit`` 默认值写死 2000，没读配置。"""
    code = _code("app/routes/history.py")
    assert "Query(2000" not in code, "limit 默认值不得写死"
    assert "log_history_default_limit" in _code("app/collectors/history.py")
    assert "Query(None" in code, "limit 应为 None，由配置决定"


def test_d3_default_limit_covers_max_range():
    """默认拉取上限必须 >= 上限，否则 journalctl 的 -n 会从旧端截断。"""
    from app.config import Settings

    s = Settings()
    assert s.log_history_default_limit >= s.log_history_max_lines


def test_d3_guard_exists():
    src = _all_test_source()
    assert "test_cache_key_includes_limit" in src
    assert "test_default_limit_covers_max_days" in src


# ===========================================================================
# D4 —— spec_types 字段被字符串替换粘连（整个字段消失）
# ===========================================================================
#: 粘连损坏的真实形态：一行里 ``#`` 注释之后**又出现了字段定义**
GLUED = re.compile(r"#.*\S+\s*:\s*[A-Za-z_][\w\[\]|. ]*\s*=")


def test_d4_spec_types_field_present():
    """原始症状：`'RuntimeConfig' object has no attribute 'spec_types'`。"""
    from app.models import RuntimeConfig

    rc = RuntimeConfig()
    assert hasattr(rc, "spec_types"), "spec_types 字段必须存在"
    assert rc.spec_types == ""


def test_d4_no_glued_field_definitions():
    """全仓扫描：不得有「注释后面还跟着字段定义」的行。

    注意：函数签名里的多个参数（``a: int = 1, b: str = ""``）是**正常**的，
    不能用"一行两个 field = "来判断（第一版审计就是这么误判的）。
    """
    bad: list[str] = []
    for p in APP.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if GLUED.search(ln) and "noqa" not in ln and "type: ignore" not in ln:
                bad.append(f"{p.relative_to(ROOT)}:{i}: {ln.strip()[:90]}")
    assert not bad, "发现注释与字段定义粘连（字段可能被吞掉）：\n" + "\n".join(bad)


def test_d4_scan_helper_is_not_fooled_by_comments():
    """自检：剥离注释后，注释里的伪代码不得被当成真实代码。"""
    sample = '"""文档里提到 if not fields: return"""\nif not fields:\n    return\n'
    stripped = _strip_py(sample)
    assert "文档里提到" not in stripped
    assert stripped.count("if not fields:") == 1, "注释里的示例不应残留"


# ===========================================================================
# D5 —— PowerShell 写入 UTF-8 BOM
# ===========================================================================
BOM = b"\xef\xbb\xbf"
BOM_PATTERNS = (
    "app/**/*.py",
    "tests/**/*.py",
    "tools/*.py",
    "probes/*.py",
    "static/*.js",
    "static/*.html",
    "static/*.css",
    "deploy/*.py",
    "docs/*.md",
    "*.sh",
    "deploy/*.sh",
)


def test_d5_no_bom_anywhere():
    """原始症状：① 源码扫描守卫失效；② shell 脚本报 No such file or directory。

    BOM 会让 ``src.startswith('\"\"\"')`` 为假 → 整个文件被当成"代码"，
    注释里的内容也会被扫描到 → 守卫给出**虚假结论**。
    """
    bad: list[str] = []
    for pat in BOM_PATTERNS:
        for p in ROOT.glob(pat):
            if p.read_bytes()[:3] == BOM:
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, "以下文件带 UTF-8 BOM，请运行 tools/strip_bom.py：\n" + "\n".join(bad)


def test_d5_strip_tool_covers_all_file_types():
    """清理工具必须覆盖所有会被 BOM 破坏的文件类型。

    **v0.5 加强**：早期实现用"文本扩展名白名单"，漏掉了 ``.csv`` 与
    **无扩展名**的文件（例如 ``deploy/sudoers.llm-console``）。
    现在改为**二进制黑名单** —— 默认认为所有文件都是文本，
    只跳过已知的二进制格式，因此覆盖范围严格更大。

    这里断言的就是"用黑名单而不是白名单"这件事本身。
    """
    src = (TOOLS / "strip_bom.py").read_text(encoding="utf-8")
    assert "BINARY_EXTS" in src, "strip_bom.py 应使用二进制黑名单"
    assert "SCAN_DIRS" in src, "strip_bom.py 应递归扫描目录"
    # 不得再用扩展名白名单（那正是漏掉 .csv / 无扩展名文件的根因）
    assert "SCAN_EXTS" not in src, "strip_bom.py 不应退回扩展名白名单 —— 那会漏掉 .csv 与无扩展名文件"
    # 关键类型必须在跳过清单里被显式排除（而不是靠白名单漏掉）
    for binary in (".docx", ".png", ".zip"):
        assert binary in src, f"strip_bom.py 应显式跳过二进制类型 {binary}"


def test_d5_line_ending_tool_uses_blacklist_too():
    """同上：行尾工具也必须用黑名单，否则漏掉 sudoers 这类无扩展名文件。"""
    src = (TOOLS / "fix_line_endings.py").read_text(encoding="utf-8")
    assert "BINARY_EXTS" in src, "fix_line_endings.py 应使用二进制黑名单"
    assert "SCAN_EXTS" not in src, "fix_line_endings.py 不应退回扩展名白名单"


def test_d5_strip_tool_is_idempotent():
    """清理工具必须幂等（重复运行不破坏文件）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("strip_bom", TOOLS / "strip_bom.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for p in ROOT.glob("tests/*.py"):
        before = p.read_bytes()
        assert not before.startswith(BOM)
        assert before == p.read_bytes()


def test_d5_guard_test_exists():
    assert "test_no_bom_in_sources" in _all_test_source()


# ===========================================================================
# D6 —— KV 量化重复标注「（默认）」
# ===========================================================================
def test_d6_badge_value_is_raw():
    """原始症状：界面显示 `f16（默认）（默认）`。

    根因：后端 badge_items 的值已含「（默认）」，前端按 source 又加一次。
    """
    from app.collectors.props import PropsCollector
    from app.config import Settings
    from app.services.unitinfo import UnitConfig

    class _Client:
        async def get_json(self, *a, **kw):  # pragma: no cover
            return None

    c = PropsCollector(Settings(), _Client())
    label, source, raw = c._kv_quant(UnitConfig(raw_exec="ExecStart=/x"), {})
    assert source == "default"
    assert "默认" in label, "中文兼容串应带标注"
    assert "默认" not in raw, "裸值不得带标注（否则前端会重复）"


def test_d6_props_uses_raw_for_badge_items():
    code = _code("app/collectors/props.py")
    assert '"key": "kv_quant", "value": kv_raw' in code, "badge_items 必须用裸值"
    assert "kv_raw" in code.split("_kv_quant", 1)[1], "解包必须取三元组"


def test_d6_frontend_adds_marker_from_source():
    """前端必须**依据 source=default** 决定是否加标注，而不是无条件加。"""
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "item.source === 'default'" in js
    assert "kv.quant.default" in js


# ===========================================================================
# D7 —— 历史缓存无界增长
# ===========================================================================
def test_d7_cache_eviction_works():
    """原始症状：控制台内存从 46 MB 涨到 88 MB。"""
    from app.collectors.history import HistoryResult, LogHistory
    from app.config import Settings

    lh = LogHistory(Settings())
    for i in range(50):
        lh._cache[(30, 100 + i)] = (float(i), HistoryResult(returned=1))
    lh._evict()
    assert len(lh._cache) <= 4, f"应裁剪到 4 条，实际 {len(lh._cache)}"
    assert (30, 149) in lh._cache, "必须保留最新条目"


def test_d7_evict_called_on_insert():
    code = _code("app/collectors/history.py")
    seg = code[code.index("async def fetch") :]
    assert "self._evict()" in seg, "插入缓存后必须调用 _evict"


def test_d7_memory_budget_documented():
    """内存预算是明确的设计取舍，必须写在代码里而不是靠记忆。"""
    code = _code("app/collectors/history.py")
    assert "内存" in (ROOT / "app/collectors/history.py").read_text(encoding="utf-8")
    assert "max_entries" in code


# ===========================================================================
# D8 —— 文档生成器给中文插零宽空格
# ===========================================================================
MDTEXT = TOOLS / "mdtext.py"


@pytest.mark.skipif(not MDTEXT.exists(), reason="tools/mdtext.py 未部署")
def test_d8_brk_only_ascii_tokens():
    """原始症状：DOCX 里「中/英切换」被插入不可见零宽空格，文本检索失真。

    根因：``brk()`` 对**每个**斜杠都插断点。修复为只处理 ASCII token 内部。

    判据针对**无依赖**的 ``tools/mdtext.py``（md2docx 需要 python-docx，
    服务器上没装），因此本用例在 目标 上也能真实执行。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("mdtext", MDTEXT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 中文不得被插入零宽空格
    assert mod.ZWSP not in mod.brk("中/英切换"), "中文词不得被插入零宽空格"
    assert mod.ZWSP not in mod.brk("KV 池 31.2%"), "含中文的行不得被改"
    assert mod.ZWSP not in mod.brk("服务日志 / 历史服务日志"), "带空格的中文斜杠不得被改"
    # 长路径仍必须可断行（原有的溢出修复不能丢）
    assert mod.ZWSP in mod.brk("/usr/include/x86_64-linux-gnu/cudnn_version.h")
    assert mod.ZWSP in mod.brk("zh/en")
    assert mod.ZWSP in mod.brk("cuda-12.8/toolkit")


@pytest.mark.skipif(not MDTEXT.exists(), reason="tools/mdtext.py 未部署")
def test_d8_plain_strips_zwsp():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mdtext2", MDTEXT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.plain("a" + mod.ZWSP + "b") == "ab"
    assert mod.plain("**粗体**") == "粗体"


@pytest.mark.skipif(not MDTEXT.exists(), reason="tools/mdtext.py 未部署")
def test_d8_disp_len_counts_cjk_as_two():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mdtext3", MDTEXT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.disp_len("ab") == 2
    assert mod.disp_len("中文") == 4


def test_d8_md2docx_uses_shared_text_module():
    """md2docx 必须复用 mdtext，不得再各自维护一份 brk（否则会再次分叉）。"""
    src = (TOOLS / "md2docx.py").read_text(encoding="utf-8")
    assert "from mdtext import" in src, "md2docx 应从 mdtext 导入文本工具"
    assert "def brk" not in src and "ZWSP = " not in src, "不得再保留本地副本"


def test_d8_tools_deployed():
    """tools/ 必须随部署上传 —— 否则文档工具的缺陷在服务器侧无法守卫。"""
    src = (ROOT / "deploy" / "upload.py").read_text(encoding="utf-8")
    m = re.search(r"INCLUDE_DIRS\s*=\s*\(([^)]*)\)", src)
    assert m, "找不到 INCLUDE_DIRS"
    assert '"tools"' in m.group(1), "INCLUDE_DIRS 必须包含 tools"


# ===========================================================================
# D9 —— 本地与远端分叉：sync 漏目录导致修复被覆盖
# ===========================================================================
#: 只上行、不回传的目录：文档在本地编写与生成，服务器只是镜像。
#: 若把服务器上的 docs 回传，反而可能覆盖本地正在编辑的源文件。
UPLOAD_ONLY_DIRS = {"docs"}


def test_d9_sync_dirs_match_upload_dirs():
    """**回归**：`sync_from_host.DIRS` 必须覆盖 `upload.INCLUDE_DIRS` 的**代码目录**。

    原始症状：在 目标 上跑 `ruff --fix` 修好了 `probes/`，但
    `sync_from_host.py` 只回传 `app/tests/static/deploy` —— 修复无法落回本地，
    下次 `upload.py` 又把未修复版本覆盖回服务器，同一个 lint 错误
    **反复出现**，看起来像"修了没用"。

    这类"单向同步丢目录"会让本地与远端静默分叉，非常难查。
    例外：``UPLOAD_ONLY_DIRS`` 里的目录是有意只上行的。
    """
    upload_src = (ROOT / "deploy" / "upload.py").read_text(encoding="utf-8")
    sync_src = (ROOT / "deploy" / "sync_from_host.py").read_text(encoding="utf-8")

    def dirs_of(src: str, name: str) -> set[str]:
        m = re.search(rf"{name}\s*=\s*\(([^)]*)\)", src)
        assert m, f"找不到 {name}"
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    up = dirs_of(upload_src, "INCLUDE_DIRS")
    sy = dirs_of(sync_src, "DIRS")
    missing = sorted(up - sy - UPLOAD_ONLY_DIRS)
    assert not missing, (
        f"sync_from_host.DIRS 缺少 {missing} —— 这些目录在服务器上做的格式化/修复无法回传本地，会造成来回分叉"
    )
    extra = sorted(sy - up)
    assert not extra, f"sync_from_host.DIRS 多出 {extra}，这些目录并未随部署上传"


def test_d9_upload_and_sync_both_cover_tools():
    """tools/ 必须既能上传也能回传（v0.4.4 的 D8 依赖它）。"""
    for rel, var in (("deploy/upload.py", "INCLUDE_DIRS"), ("deploy/sync_from_host.py", "DIRS")):
        src = (ROOT / rel).read_text(encoding="utf-8")
        m = re.search(rf"{var}\s*=\s*\(([^)]*)\)", src)
        assert m and '"tools"' in m.group(1), f"{rel} 的 {var} 必须含 tools"
