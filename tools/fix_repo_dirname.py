"""把「克隆后的目录名 / 部署根目录」与仓库新名对齐（v0.6）。

    python tools/fix_repo_dirname.py --apply

仓库从 ``wkl-llm-ops`` 改名为 ``WKL-LLM-Ops-Platform`` 之后，
``git clone`` 生成的目录名、压缩包解压后的目录名都随之改变。
文档里如果还写 ``cd wkl-llm-ops``，用户**照抄就会失败**。

本工具只改这些「会随仓库名变化的路径」，不碰：
  * Python 发行包名 ``wkl-llm-ops``（独立于 GitHub 仓库名，继续沿用）
  * 一次性迁移工具里的品牌映射表
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
SCAN_DIRS = ("tests", "tools", "probes", "deploy", "docs", "static", ".github", "app")
ROOT_FILES = (
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.zh-CN.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "AGENTS.md",
    "AGENTS.zh-CN.md",
    "install.sh",
    "update.sh",
    "uninstall.sh",
    "selfcheck.sh",
)
BINARY_EXTS = {".docx", ".xlsx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".gif"}

#: 一次性迁移工具按设计含旧名，不参与
SELF = {
    "tools/fix_repo_dirname.py",
    "tools/rename_brand.py",
    "tools/rename_docs.py",
    "tools/rename_docx.py",
    "tools/fix_repo_url.py",
}

NEW_DIR = "WKL-LLM-Ops-Platform"

RULES: list[tuple[str, str, str]] = [
    # 压缩包解压后的目录名（GitHub 生成的 name-main）
    ("wkl-llm-ops-main", f"{NEW_DIR}-main", "压缩包解压目录"),
    # 相对路径使用（cd / mv / rm -rf）
    ("wkl-llm-ops", NEW_DIR, "相对目录名"),
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
        # Python 发行包名要保持 wkl-llm-ops，不参与替换
        guard = []
        if rel == "pyproject.toml":
            continue  # 包名独立于仓库名
        orig, hits = text, 0
        for old, new, _why in RULES:
            n = text.count(old)
            if n:
                text = text.replace(old, new)
                hits += n
        del guard
        if text != orig:
            changed.append((rel, hits))
            if apply:
                p.write_text(text, encoding="utf-8", newline="\n")

    print(f"=== {'已修改' if apply else '待修改'} {len(changed)} 个文件 ===")
    for rel, n in sorted(changed):
        print(f"  {rel}  ({n} 处)")

    print("\n=== 残留（应只剩包名与一次性工具）===")
    for p in iter_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in SELF:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(lines, 1):
            if "wkl-llm-ops" in ln:
                print(f"  {rel}:{i}: {ln.strip()[:100]}")

    print(f"\nFIX_DIRNAME_{'APPLIED' if apply else 'DRYRUN'}: {NEW_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
