"""清理 UTF-8 BOM（v0.4.3 工具，v0.5 扩大扫描范围）。

背景：用 PowerShell 的 ``Set-Content -Encoding UTF8`` 在部分环境会写入 BOM
（``EF BB BF``）。后果都不轻：

* Python 源码带 BOM 会让"首行是文档字符串"的判断失效
  （``src.startswith('\"\"\"')`` 为假），进而**破坏所有基于源码扫描的守卫测试**
* JS/CSS 带 BOM 会让浏览器首行解析出现意外
* shell 脚本带 BOM 会让 ``#!/usr/bin/env bash`` 变成
  ``\\ufeff#!/usr/bin/env bash``，内核找不到解释器，
  报 "No such file or directory"（实测踩过的坑）
* CSV 数据文件带 BOM 会让下游解析器把第一列列名读成 ``\\ufeff0``

**扫描范围**：``SCAN_DIRS`` 下所有非二进制文件 + 根目录的若干文件。
早期版本用扩展名白名单，漏掉了 ``.csv`` 与无扩展名文件
（例如 ``deploy/sudoers.llm-console``），因此改为**二进制黑名单**。

本脚本幂等。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

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
BOM = b"\xef\xbb\xbf"


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
    fixed: list[str] = []
    for p in iter_files():
        raw = p.read_bytes()
        if raw.startswith(BOM):
            p.write_bytes(raw[len(BOM) :])
            fixed.append(str(p.relative_to(ROOT)))
    print(f"BOM 清理完成：{len(fixed)} 个文件")
    for f in fixed:
        print("  -", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
