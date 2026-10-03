"""【反写死守卫】v0.4 §9.1 —— 保证换服务器也能用。

这是本次升级最关键的一组测试：v0.1 正是因为把 目标 的型号/路径/基线写死，
才无法部署到别的机器。本文件做两类断言：

  A. 静态扫描：生产代码（app/ + static/）中**不得出现**特定部署的字面量；
  B. 数据表完整性：gpu_spec 的型号表必须能覆盖常见卡型，且未收录时返回 None。

白名单只允许注释与文档字符串（它们是说明，不是"事实"）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
STATIC = ROOT / "static"

#: 禁止出现在**生产代码**中的字面量模式。
#:
#: 用**正则模式**而不是具体取值：这样守卫本身不含任何真实部署信息
#: （仓库开源后依然干净），但依然能拦住"把某台机器的数据写进代码"这类缺陷。
FORBIDDEN: dict[str, str] = {
    r"\bV100_BANDWIDTH\w*": "写死的显卡带宽常量",
    r"/home/(?!llmops\b)[A-Za-z0-9._-]+/": "开发者本机主目录路径",
    r"/Users/[A-Za-z0-9._-]+/": "开发者本机主目录路径（macOS）",
    r"\b(?:10|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b": "内网私有 IP",
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b": "内网私有 IP（172.16/12）",
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b": "真实邮箱地址",
}

#: 允许出现在注释/文档字符串里的说明性词（这些是解释，不是事实）
COMMENT_OK = ("Tesla V100", "V100", "253")


def _strip_comments_and_docstrings(src: str) -> str:
    """去掉 Python 注释与文档字符串，只保留可执行代码。

    注意先去掉可能的 UTF-8 BOM —— 否则 ``src.startswith('\"\"\"')`` 判不出
    首行文档字符串，整个文件会被当成"代码"，扫描结果不可信
    （实测踩过的坑，见 ``test_no_bom_in_sources``）。
    """
    src = src.lstrip("\ufeff")
    out_lines = []
    in_doc = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc if s.count('"""') == 1 or s.count("'''") == 1 else in_doc
            continue
        if in_doc:
            continue
        code = line.split("#", 1)[0]
        if code.strip():
            out_lines.append(code)
    return "\n".join(out_lines)


def test_no_bom_in_sources():
    """源码不得带 UTF-8 BOM。

    实测踩过的坑：用 PowerShell 的 ``Set-Content -Encoding UTF8`` 写文件会
    引入 BOM，导致"首行是文档字符串"的判断失效，进而让本文件全部基于源码
    扫描的守卫用例失去意义。JS/CSS 带 BOM 也会影响浏览器解析。
    """
    pats = (
        "app/**/*.py",
        "tests/**/*.py",
        "tools/*.py",
        "probes/*.py",
        "static/*.js",
        "static/*.html",
        "static/*.css",
        "deploy/*.py",
        "*.sh",
        "deploy/*.sh",
    )
    bad: list[str] = []
    for pat in pats:
        for p in ROOT.glob(pat):
            if p.read_bytes()[:3] == b"\xef\xbb\xbf":
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, "以下文件带 UTF-8 BOM，请运行 tools/strip_bom.py：\n" + "\n".join(bad)


def _py_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_deployment_literals_in_python():
    """生产 Python 代码不得含开发者本机路径 / 内网 IP / 写死的硬件常量。"""
    bad: list[str] = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        code = _strip_comments_and_docstrings(src)
        for pattern, why in FORBIDDEN.items():
            m = re.search(pattern, code)
            if m:
                bad.append(f"{p.relative_to(ROOT)}: 命中 {m.group(0)!r}（{why}）")
    assert not bad, "发现写死的部署信息：\n" + "\n".join(bad)


def test_no_hardcoded_baseline_in_config():
    """告警基线不得有写死的默认值（v0.4 F4）—— 必须来自自动学习或人工覆盖。"""
    src = (APP / "config.py").read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(src)
    # mtp_accept_baseline / decode_baseline_tps 必须默认为 None
    assert re.search(r"mtp_accept_baseline:\s*float\s*\|\s*None\s*=\s*None", code), (
        "mtp_accept_baseline 默认值必须为 None（自动学习），不得写死数值"
    )
    assert re.search(r"decode_baseline_tps:\s*float\s*\|\s*None\s*=\s*None", code), (
        "decode_baseline_tps 默认值必须为 None（自动学习），不得写死数值"
    )
    # 不得再出现绝对路径默认值
    assert "/home/llmops" not in code, "config.py 仍写死了部署绝对路径（F8）"


def test_state_dir_is_self_locating():
    """state_dir 必须由 __file__ 推导，而不是写死路径（v0.4 F8）。"""
    from app.config import PKG_ROOT

    assert PKG_ROOT.name  # 非空
    assert (APP / "config.py").exists()
    # PKG_ROOT 应该是项目根（app 的上一级）
    assert (PKG_ROOT / "app").is_dir()


def test_no_hardcoded_gpu_bandwidth():
    """gpu.py 不得再出现 V100 专用带宽常量与风扇恒空（v0.4 F2/F3）。"""
    src = (APP / "collectors" / "gpu.py").read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(src)
    assert "900.0" not in code, "gpu.py 仍写死带宽 900（应查 gpu_spec 表）"
    assert "V100_BANDWIDTH_GBPS" not in code
    assert "fan.speed" in code, "必须实际查询 fan.speed（F3）"


def test_no_hardcoded_power_watt():
    """功耗告警必须相对 power_limit，不得写死绝对瓦数（F7）。"""
    src = (APP / "services" / "alerts.py").read_text(encoding="utf-8")
    assert "power_warn_w" not in src, "仍在使用写死的 power_warn_w"
    assert "power_warn_pct" in src
    assert "power_limit_w" in src


def test_sudoers_hint_has_no_hardcoded_user():
    """sudoers 提示必须动态取用户名（F9）。"""
    src = (APP / "services" / "service_ctl.py").read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(src)
    assert "llmops" not in code, "sudoers 提示仍写死用户名"
    assert "getpass" in src or "getuser" in src
    assert "reset-failed" in src, "白名单应包含 reset-failed"


def test_frontend_has_no_business_literals():
    """前端不得含业务字面量：文案与阈值都必须由后端下发（F5/F15/F16）。"""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    live = "\n".join(ln for ln in js.splitlines() if not ln.strip().startswith(("//", "*", "/*")))
    for token in ("-kvu", "统一池", "platform", "lastRefresh2"):
        assert token not in live, f"app.js 仍含 {token!r}（应改为后端下发）"
    # 阈值必须走 th()
    for key in ("vram_crit_pct", "kv_crit_pct", "gpu_temp_warn_c", "power_warn_pct"):
        assert f"th('{key}'" in js, f"前端未使用后端阈值 {key}"


def test_frontend_hardcodes_no_threshold_numbers():
    """前端不得出现阈值魔法数字（95/85/87/83 直接比较）。"""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    live = "\n".join(ln for ln in js.splitlines() if not ln.strip().startswith(("//", "*", "/*")))
    for pat in (r">\s*95\b", r">\s*85\b", r">\s*87\b", r">\s*83\b"):
        assert not re.search(pat, live), f"前端仍硬编码阈值比较：{pat}"


@pytest.mark.parametrize(
    "model,expected",
    [
        ("Tesla V100-SXM2-16GB", 900.0),
        ("NVIDIA A100-SXM4-80GB", 1555.0),
        ("NVIDIA H100 PCIe", 3350.0),
        ("NVIDIA GeForce RTX 4090", 1008.0),
        ("AMD Instinct MI210", 1638.0),
    ],
)
def test_gpu_spec_covers_common_cards(model, expected):
    from app.services.gpu_spec import bandwidth_of

    assert bandwidth_of(model) == expected


def test_gpu_spec_unknown_returns_none_not_a_default():
    """未收录型号必须返回 None —— 这是 F2 的核心（不得套用别的卡的值）。"""
    from app.services.gpu_spec import (
        bandwidth_label,
        bandwidth_of,
        lookup,
        mem_type_of,
        vendor_of,
    )

    for name in ("Some Mystery Accelerator 9000", "FooBar XPU", "", "   "):
        assert bandwidth_of(name) is None, f"{name!r} 不应返回带宽"
        assert lookup(name) is None
        assert mem_type_of(name) == ""
        assert vendor_of(name) == ""
    assert "未知" in bandwidth_label("Some Mystery Accelerator 9000")
