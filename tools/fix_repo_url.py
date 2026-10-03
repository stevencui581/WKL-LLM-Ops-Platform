"""把仓库地址统一为正式地址（v0.6）。

    python tools/fix_repo_url.py            # 只报告
    python tools/fix_repo_url.py --apply    # 就地修改

正式地址 / canonical home:
    https://github.com/stevencui581/WKL-LLM-Ops-Platform

覆盖所有形态：
    * ``https://github.com/<org>/<repo>``
    * ``https://raw.githubusercontent.com/<org>/<repo>``（一键脚本的 curl 地址）
    * ``https://github.com/<org>/<repo>.git``（clone 地址）
    * 裸的 ``<org>/<repo>``（徽章等）

**注意**：只替换本项目的旧地址。文档里引用的**第三方**仓库
（参考项目、规范来源）必须原样保留。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NEW_ORG = "stevencui581"
NEW_REPO = "WKL-LLM-Ops-Platform"
OLD_ORG = "wkl-llm"
OLD_REPO = "wkl-llm-ops"

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

#: 本工具自身按设计含旧地址，不参与替换
SELF = {"tools/fix_repo_url.py"}

RULES: list[tuple[str, str, str]] = [
    # 长的先替换，避免 .git 后缀被前面的规则吃掉后剩下悬空的 ".git"
    (
        f"https://github.com/{OLD_ORG}/{OLD_REPO}.git",
        f"https://github.com/{NEW_ORG}/{NEW_REPO}.git",
        "clone 地址（含 .git）",
    ),
    (
        "https://raw.githubusercontent.com/" + f"{OLD_ORG}/{OLD_REPO}",
        "https://raw.githubusercontent.com/" + f"{NEW_ORG}/{NEW_REPO}",
        "raw 地址（一键脚本用）",
    ),
    (f"https://github.com/{OLD_ORG}/{OLD_REPO}", f"https://github.com/{NEW_ORG}/{NEW_REPO}", "仓库主页"),
    (f"{OLD_ORG}/{OLD_REPO}", f"{NEW_ORG}/{NEW_REPO}", "裸 owner/repo（徽章等）"),
]


def iter_files():
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


def main() -> int:
    apply = "--apply" in sys.argv
    changed: list[tuple[str, int]] = []
    for p in iter_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in SELF:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        orig, hits = text, 0
        for old, new, _why in RULES:
            n = text.count(old)
            if n:
                text = text.replace(old, new)
                hits += n
        if text != orig:
            changed.append((rel, hits))
            if apply:
                p.write_text(text, encoding="utf-8", newline="\n")

    print(f"=== {'已修改' if apply else '待修改'} {len(changed)} 个文件 ===")
    for rel, n in sorted(changed):
        print(f"  {rel}  ({n} 处)")

    print("\n=== 残留旧地址检查 ===")
    residue: list[str] = []
    for p in iter_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in SELF:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if OLD_ORG in text or OLD_REPO in text:
            for i, ln in enumerate(text.splitlines(), 1):
                if OLD_ORG in ln or OLD_REPO in ln:
                    residue.append(f"{rel}:{i}: {ln.strip()[:100]}")
    print("\n".join(f"  {r}" for r in residue[:20]) if residue else "  （无）")

    print("\n=== 第三方地址应保持不变（核对）===")
    for p in iter_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(text.splitlines(), 1):
            if any(
                t in ln
                for t in (
                    "promptfoo/promptfoo",
                    "NousResearch/hermes-agent",
                    "weicj/vLLM-2080Ti-Definitive",
                    "openjs-foundation",
                )
            ):
                print(f"  {p.relative_to(ROOT)}:{i}: {ln.strip()[:90]}")
                break

    print(f"\nFIX_URL_{'APPLIED' if apply else 'DRYRUN'}: {NEW_ORG}/{NEW_REPO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
