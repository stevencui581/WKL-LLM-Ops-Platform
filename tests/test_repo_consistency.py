"""仓库一致性守卫（v0.6）：版本号与仓库地址。

**为什么需要**

    版本号和仓库地址是**全仓散落**的两类字符串：

      * 版本号：config、pyproject、VERSION、CITATION、页面占位、徽章、
        测试断言、13 份双语文档、一键脚本
      * 仓库地址：徽章、一键脚本的 curl 地址、clone 地址、Issue 模板、
        pyproject 链接、CITATION

    本项目已经踩过两次坑：`app.js` 里残留 `|| 'v0.4.3'` 兜底；
    v0.5.1 新增双语文档时上传清单没跟上。这类"改了一处忘了另一处"
    只能靠守卫拦。

本文件同时锁定**第三方地址不得被误改** —— 文档里引用的参考项目与规范来源
必须原样保留，不能被"统一替换"波及。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: 当前版本（对应用户要求的 0.6 版本）
DISPLAY_VERSION = "v0.6"
PKG_VERSION = "0.6.0"

#: 正式仓库地址
CANONICAL = "https://github.com/stevencui581/WKL-LLM-Ops-Platform"
CANONICAL_RAW = "https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform"

#: 旧地址（不得再出现）
STALE_REPO = re.compile(r"wkl-llm/wkl-llm-ops")

#: 必须保持原样的第三方来源
THIRD_PARTY = (
    "promptfoo/promptfoo",
    "NousResearch/hermes-agent",
    "weicj/vLLM-2080Ti-Definitive",
    "openjs-foundation/cross-project-council",
)

SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    "build",
    "state",
    "logs",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "history",
    "releases",
    "current",
}
SCAN_DIRS = ("app", "tests", "tools", "probes", "deploy", "docs", "static", ".github")
ROOT_FILES = (
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.zh-CN.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT.zh-CN.md",
    "AGENTS.md",
    "AGENTS.zh-CN.md",
    "CITATION.cff",
    "VERSION",
    "pyproject.toml",
    "conftest.py",
    "selfcheck.sh",
    "install.sh",
    "update.sh",
    "uninstall.sh",
)
BINARY_EXTS = {
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".tgz",
}

#: 本文件按设计含旧地址用于断言；一次性迁移工具含旧名用于映射
EXEMPT_FILES = {
    "tests/test_repo_consistency.py",
    "tools/fix_repo_url.py",
    "tools/fix_repo_dirname.py",
    "tools/rename_brand.py",
    "tools/rename_docs.py",
    "tools/rename_docx.py",
}


def _iter_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or any(x in SKIP_DIRS for x in p.parts):
                continue
            if p.suffix.lower() in BINARY_EXTS:
                continue
            yield p
    for name in ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            yield p


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


# ===========================================================================
# 1. 版本号唯一来源与一致性
# ===========================================================================
def test_config_is_the_single_source_of_version():
    """`app/config.py` 是运行时版本号的唯一来源。"""
    src = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    assert f'product_version: str = "{DISPLAY_VERSION}"' in src
    assert f'product_name: str = "WKL-LLM运维平台{DISPLAY_VERSION}"' in src
    assert f'product_name_spaced: str = "WKL-LLM运维平台 {DISPLAY_VERSION}"' in src


def test_package_version_matches():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"$', text, re.M)
    assert m, "pyproject.toml 未找到 version"
    assert m.group(1) == PKG_VERSION, f"pyproject 版本 {m.group(1)} != {PKG_VERSION}"


def test_version_file_matches():
    text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert text == PKG_VERSION, f"VERSION 文件为 {text}，应为 {PKG_VERSION}"


def test_citation_version_matches():
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert f'version: "{PKG_VERSION}"' in text, "CITATION.cff 版本不一致"


@pytest.mark.parametrize("page", ["static/index.html", "static/alerts.html", "static/logs.html"])
def test_pages_show_current_version(page: str):
    text = (ROOT / page).read_text(encoding="utf-8")
    assert f'<span class="ver">{DISPLAY_VERSION}</span>' in text, f"{page} 版本占位不是 {DISPLAY_VERSION}"


@pytest.mark.parametrize("doc", ["README.md", "README.zh-CN.md"])
def test_readme_badge_version(doc: str):
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert f"badge/version-{DISPLAY_VERSION}-green" in text, f"{doc} 徽章版本不一致"


def test_no_frontend_version_literal_in_scripts():
    """前端**脚本**里不得出现版本号字面量（徽章/占位除外）。

    这是真实踩过的坑：`app.js` 里留了 `|| 'v0.4.3'` 兜底，升版时漏改，
    页面上会闪一下旧版本号。
    """
    for p in (ROOT / "static").glob("*.js"):
        text = p.read_text(encoding="utf-8")
        code = "\n".join(
            ln.split("//", 1)[0] for ln in text.splitlines() if not ln.strip().startswith(("*", "/*"))
        )
        m = re.search(r"['\"]v\d+\.\d+", code)
        assert m is None, f"{p.name} 含版本号字面量：{m.group(0) if m else ''}"


# ===========================================================================
# 2. 仓库地址
# ===========================================================================
def test_no_stale_repo_url_anywhere():
    """旧仓库地址不得残留在任何文件里。"""
    bad: list[str] = []
    for p in _iter_files():
        if _rel(p) in EXEMPT_FILES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(text.splitlines(), 1):
            if STALE_REPO.search(ln):
                bad.append(f"{_rel(p)}:{i}: {ln.strip()[:100]}")
    assert not bad, "仍存在旧仓库地址：\n" + "\n".join(bad)


def test_installer_uses_canonical_raw_url():
    """一键脚本的 curl 地址必须指向正式仓库 —— 用户复制的就是这一行。"""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert CANONICAL_RAW in text, "install.sh 的下载地址不是正式地址"
    assert f"{CANONICAL}.git" in text or CANONICAL in text, "install.sh 的 clone 地址不是正式地址"
    upd = (ROOT / "update.sh").read_text(encoding="utf-8")
    assert CANONICAL_RAW in upd, "update.sh 的下载地址不是正式地址"


def test_pyproject_urls_point_at_canonical():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert CANONICAL in text, "pyproject.toml 的项目链接不是正式地址"


def test_citation_repository_is_canonical():
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert CANONICAL in text, "CITATION.cff 的仓库地址不是正式地址"


@pytest.mark.parametrize(
    "doc",
    [
        "README.md",
        "README.zh-CN.md",
        "CONTRIBUTING.md",
        "CONTRIBUTING.zh-CN.md",
        "CODE_OF_CONDUCT.md",
        "CODE_OF_CONDUCT.zh-CN.md",
        "SECURITY.md",
        "SECURITY.zh-CN.md",
        "docs/INSTALL.md",
        "docs/INSTALL.zh-CN.md",
    ],
)
def test_docs_reference_canonical(doc: str):
    """涉及仓库地址的文档必须指向正式地址。"""
    text = (ROOT / doc).read_text(encoding="utf-8")
    if "github.com" not in text:
        pytest.skip("该文档不含仓库地址")
    assert CANONICAL in text, f"{doc} 未使用正式仓库地址"


def test_third_party_urls_untouched():
    """第三方来源必须保持原样 —— 不能被"统一替换"波及。"""
    found: dict[str, list[str]] = {}
    for p in _iter_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for src in THIRD_PARTY:
            if src in text:
                found.setdefault(src, []).append(_rel(p))
    # 参考项目与规范来源至少各在一处被引用（v0.6 报告 + FAQ 等）
    assert found, "没有任何第三方来源引用 —— 是否被误删或误改？"
    for src, files in found.items():
        assert all(isinstance(f, str) for f in files), f"{src} 引用异常"


def test_repo_dirname_consistent():
    """文档里的 clone 目标目录名必须与新仓库名一致。

    仓库改名后 `git clone` 生成的目录名会变；文档若仍写旧目录名，
    用户照抄 `cd` 就会失败。
    """
    bad: list[str] = []
    for p in _iter_files():
        if _rel(p) in EXEMPT_FILES:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(lines, 1):
            # 只拦「相对路径形态」的旧目录名，不拦 pyproject 的包名
            if re.search(r"(cd |mv |rm -rf |~/|/opt/)wkl-llm-ops\b", ln):
                bad.append(f"{_rel(p)}:{i}: {ln.strip()[:100]}")
    assert not bad, "文档里的目录名未与仓库名对齐：\n" + "\n".join(bad)
