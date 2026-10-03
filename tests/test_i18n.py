"""多语言守卫测试（v0.4.3 §8.1 / TASK-61）。

本文件是整个双语改造的**质量闸门**，核心断言只有三条，但极其有效：

  1. ``zh`` 与 ``en`` 的 key 集合**完全一致** —— 谁漏翻译一条立刻失败；
  2. ``en`` 的值**不含任何 CJK 字符** —— 谁在英文译文里手滑写了中文立刻失败；
  3. HTML/JS 里用到的每个 i18n key 都**确实存在**于字典 —— 防止拼错 key 后
     界面上直接显示成 key 名。

第 2 条是人工点页面检查永远做不到的：它把"英文模式无中文残留"变成可自动验证的事实。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")

#: 允许在**所有**语言里都用中文的 key。
#: 语言按钮上的「中」是语言的自称（endonym），任何语言界面下都写「中」，
#: 这是通用做法（类比英文界面里的 "Français" / "Deutsch"）。
CJK_ALLOWED_IN_EN = {"lang.zh"}


# ---------------------------------------------------------------- 解析字典
def _read_i18n() -> str:
    return (STATIC / "i18n.js").read_text(encoding="utf-8")


def _extract_dict(src: str, name: str) -> dict[str, str]:
    """从 i18n.js 里提取 zh / en 两个字典。

    用花括号配平定位块边界，再按 ``'key': 'value',`` 抽取，
    比纯正则更容易定位错配。
    """
    m = re.search(rf"\b{name}:\s*\{{", src)
    assert m, f"找不到 {name} 字典"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                block = src[i + 1 : j]
                break
    else:  # pragma: no cover
        raise AssertionError(f"{name} 字典花括号不配平")
    out: dict[str, str] = {}
    for km in re.finditer(r"'([A-Za-z0-9_.]+)'\s*:\s*'((?:[^'\\]|\\.)*)'", block):
        out[km.group(1)] = km.group(2)
    return out


@pytest.fixture(scope="module")
def dicts() -> tuple[dict[str, str], dict[str, str]]:
    src = _read_i18n()
    return _extract_dict(src, "zh"), _extract_dict(src, "en")


# ===========================================================================
# 1. 结构一致性
# ===========================================================================
def test_dicts_are_not_empty(dicts):
    zh, en = dicts
    assert len(zh) > 120, f"中文词条太少（{len(zh)}），可能有解析问题"
    assert len(en) > 120


def test_key_sets_identical(dicts):
    """**核心断言**：两个语言的 key 必须一一对应。"""
    zh, en = dicts
    missing_in_en = sorted(set(zh) - set(en))
    missing_in_zh = sorted(set(en) - set(zh))
    assert not missing_in_en, f"英文缺少词条：{missing_in_en}"
    assert not missing_in_zh, f"中文缺少词条：{missing_in_zh}"


# ===========================================================================
# 2. 英文不得含中文（最强的一条）
# ===========================================================================
def test_english_dict_has_no_cjk(dicts):
    """**核心断言**：英文译文里出现任何中日韩字符都视为失败。

    例外只有语言自称（见 ``CJK_ALLOWED_IN_EN``）。
    """
    _, en = dicts
    bad = {k: v for k, v in en.items() if CJK.search(v) and k not in CJK_ALLOWED_IN_EN}
    assert not bad, "英文词典里出现了中文字符：\n" + "\n".join(f"  {k} = {v!r}" for k, v in bad.items())


def test_cjk_allowlist_is_small_and_documented(dicts):
    """白名单必须保持极小 —— 防止有人用它绕过"英文无中文"的约束。"""
    assert len(CJK_ALLOWED_IN_EN) <= 2, "CJK 白名单过大，请审查是否在放水"


def test_chinese_dict_actually_chinese(dicts):
    """反向检查：中文词典确实以中文为主（防止误把英文抄进 zh）。"""
    zh, _ = dicts
    has_cjk = sum(1 for v in zh.values() if CJK.search(v))
    assert has_cjk >= 100, f"中文词典里仅 {has_cjk} 条含中文，可能被误填成英文"


# ===========================================================================
# 3. 术语（甲方指定）
# ===========================================================================
def test_compute_card_term(dicts):
    """「算力卡」英文必须是 compute card（v0.4.3 §5）。"""
    zh, en = dicts
    assert zh["top.accel"] == "算力卡"
    assert en["top.accel"].lower() == "compute card"
    assert en["hw.accel"].lower() == "compute card"
    assert en["hw.sec2"].lower().startswith("(2) compute cards")
    # 不得出现混用译法
    for k in (
        "top.accel",
        "hw.accel",
        "hw.sec2",
        "hw.accel_detail",
        "hw.no_accel",
        "sub.no_gpu",
        "card.util",
        "card.temp",
        "card.power",
    ):
        v = en[k].lower()
        assert "accelerator card" not in v, f"{k} 混用了 accelerator card"
        assert "gpu card" not in v, f"{k} 混用了 gpu card"


def test_language_switch_labels(dicts):
    zh, en = dicts
    assert zh["lang.zh"] == "中" and en["lang.zh"] == "中"  # 语言名保持自身语言
    assert zh["lang.en"] == "EN" and en["lang.en"] == "EN"
    assert "自动" in zh["lang.auto"] and "Auto" in en["lang.auto"]
    assert "恢复自动" in zh["lang.restore"] and "Restore" in en["lang.restore"]


def test_history_page_headline(dicts):
    """历史页顶部文字必须随天数变化（v0.4.3 §3.1）。"""
    zh, en = dicts
    assert zh["lg.showing"] == "显示最近 {n} 天日志"
    assert "{n}" in en["lg.showing"] and "last" in en["lg.showing"]


def test_alert_log_columns(dicts):
    """告警日志页三列（v0.4.3 §6.1）。"""
    zh, en = dicts
    assert zh["al.col.time"] == "告警日期时间"
    assert zh["al.col.category"] == "告警服务类型"
    assert zh["al.col.name"] == "告警服务名称"
    for k in ("al.col.time", "al.col.category", "al.col.name"):
        assert en[k] and not CJK.search(en[k])


# ===========================================================================
# 4. 页面用到的 key 都存在
# ===========================================================================
def _html_i18n_keys() -> set[str]:
    keys: set[str] = set()
    for name in ("index.html", "alerts.html", "logs.html"):
        p = STATIC / name
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        for attr in ("data-i18n", "data-i18n-placeholder", "data-i18n-title", "data-i18n-option"):
            keys |= set(re.findall(rf'{attr}="([^"]+)"', src))
    return keys


def _strip_js_comments(src: str) -> str:
    """去掉 // 行注释与 /* */ 块注释。

    必须去掉：注释里写示例 ``t('key', {...})`` 会被 key 扫描误当成真实调用。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())


def _js_i18n_keys() -> set[str]:
    keys: set[str] = set()
    for name in ("app.js", "alerts.js", "logs.js", "i18n.js"):
        p = STATIC / name
        if not p.exists():
            continue
        src = _strip_js_comments(p.read_text(encoding="utf-8"))
        keys |= set(re.findall(r"\bt\(\s*'([A-Za-z0-9_.]+)'", src))
        keys |= set(re.findall(r'\bt\(\s*"([A-Za-z0-9_.]+)"', src))
    return keys


def _is_dynamic(key: str) -> bool:
    """动态拼接的 key 前缀（如 ``t('health.' + code)``）。

    这类 key 在源码里只出现前缀，真正取值在运行期拼出来，
    由 ``test_dynamic_prefixes_are_covered`` 单独校验覆盖情况。
    """
    return key.endswith(".")


def test_html_keys_exist(dicts):
    zh, _ = dicts
    missing = sorted(k for k in _html_i18n_keys() if k not in zh and not _is_dynamic(k))
    assert not missing, f"HTML 引用了不存在的 i18n key：{missing}"


def test_js_keys_exist(dicts):
    zh, _ = dicts
    missing = sorted(k for k in _js_i18n_keys() if k not in zh and not _is_dynamic(k))
    assert not missing, f"JS 引用了不存在的 i18n key：{missing}"


def test_dynamic_prefixes_are_covered(dicts):
    """动态前缀必须有实际词条支撑，否则运行期会退化成显示 key。"""
    zh, _ = dicts
    prefixes = sorted(k for k in (_html_i18n_keys() | _js_i18n_keys()) if _is_dynamic(k))
    assert prefixes, "预期存在动态前缀（health. / hw.hint.）"
    for pre in prefixes:
        assert any(k.startswith(pre) for k in zh), f"动态前缀 {pre!r} 没有任何词条"


def test_comment_stripper_works():
    """自检：注释剥离确实生效（否则上面的 key 扫描会被注释污染）。"""
    src = "var a = 1; // t('bogus.one')\n/* t('bogus.two') */\nvar b = t('real.key');"
    keys = set(re.findall(r"\bt\(\s*'([A-Za-z0-9_.]+)'", _strip_js_comments(src)))
    assert keys == {"real.key"}, keys


# ===========================================================================
# 5. 语言解析行为（用 Node 跑真实 i18n.js）
# ===========================================================================
def test_language_detection_with_node():
    """在 Node 里跑真实的 i18n.js，验证 §4.1 的解析优先级。

    目标 上没有 Node，因此这里会跳过；同一脚本可在开发机上单独执行：
    ``node tools/check_lang_detect.js``
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node 不可用（253 未安装）；请用 tools/check_lang_detect.js 单独验证")
    script = ROOT / "tools" / "check_lang_detect.js"
    proc = subprocess.run(
        [node, str(script), str(STATIC / "i18n.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "LANGDETECT_OK" in out, out
