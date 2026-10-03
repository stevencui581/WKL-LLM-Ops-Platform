"""把仓库内文本文件统一为 LF 行尾（v0.5 第 2 步）。

    python tools/fix_line_endings.py [--check]

**为什么必须有这个工具**
    在 Windows 上用 Python 的 ``Path.write_text()`` 修改文件时，**默认会做
    平台换行转换**（``\\n`` → ``\\r\\n``）。结果是：本地看着没问题，
    文件传到 Linux 后 shell 脚本直接报
    ``set: pipefail: invalid option name`` —— 因为 bash 把 ``pipefail\\r``
    当成了一个选项名。

    这是"在 Windows 上做 Linux 项目"最容易踩、又最难一眼看出的坑之一，
    所以既有归一化工具，也有对应的守卫测试（``test_line_endings.py``）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ("app", "tests", "tools", "probes", "deploy", "docs", "static")
SKIP_DIRS = {"__pycache__", ".venv", ".git", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
ROOT_FILES = (
    ".gitignore",
    "README.md",
    "README.en.md",
    "pyproject.toml",
    "conftest.py",
    "selfcheck.sh",
)

#: **二进制扩展名黑名单**。
#:
#: 早期版本用的是"文本扩展名白名单"，结果漏掉了 ``.csv`` 与**无扩展名**的文件
#: （例如 ``deploy/sudoers.llm-console``）。后者带 CRLF 会**直接破坏 sudoers 解析**，
#: 是静默的部署故障。因此改为黑名单：默认认为所有文件都是文本。
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
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".pyc",
    ".pyo",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp3",
    ".mp4",
    ".webm",
}


def iter_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.suffix.lower() in BINARY_EXTS:
                continue
            yield p
    for name in ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            yield p


def main() -> int:
    check_only = "--check" in sys.argv
    crlf: list[str] = []
    fixed = 0

    for p in iter_files():
        raw = p.read_bytes()
        if b"\r\n" not in raw:
            continue
        rel = str(p.relative_to(ROOT))
        crlf.append(rel)
        if not check_only:
            # 只把 CRLF 换成 LF，不动其它字节（避免破坏 BOM 判定顺序）
            p.write_bytes(raw.replace(b"\r\n", b"\n"))
            fixed += 1

    if crlf:
        print(f"发现 {len(crlf)} 个 CRLF 文件：")
        for rel in crlf:
            print(f"  {rel}")
    if check_only:
        print()
        print(f"LINE_ENDINGS_FAILED: {len(crlf)} 个文件不是 LF" if crlf else "LINE_ENDINGS_OK")
        return 1 if crlf else 0

    print(f"\nLINE_ENDINGS_FIXED: 归一化 {fixed} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
