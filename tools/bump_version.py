"""版本号升级（v0.6）—— 只改「当前版本」的表示。

    python tools/bump_version.py --apply

**为什么要精确规则而不是全文替换**

    项目里有两类版本号，含义完全不同：

      * **当前版本** —— `product_version`、页面占位、徽章、pyproject、VERSION、
        测试断言、文档里的"预期输出"。这些**必须**跟着升级。
      * **历史标注** —— 「（v0.5 新增）」「v0.4.3 踩过的坑」「v0.5 §1」、
        更新日志里旧版本的条目。这些**必须保留原文** ——
        改掉就等于声称"这个功能是 v0.6 才加的"，是在撒谎。

    早期用宽松正则做过一次演练，结果 56 个文件里有大半是历史注释被误改。
    因此本工具只列**精确到上下文的规则**，改完再把剩余命中逐条列出来人工判定。
"""

from __future__ import annotations

import re
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

#: 本工具自身不参与替换（它按设计含旧版本串）
SELF = {"tools/bump_version.py"}

#: (正则, 替换, 说明) —— **精确到上下文**，只匹配"当前版本"的表示
RULES: list[tuple[str, str, str]] = [
    # ---- 1. 运行时配置（唯一事实源）----
    (r'product_version: str = "v0\.5\.1"', 'product_version: str = "v0.6"', "config product_version"),
    (
        r'product_name: str = "WKL-LLM运维平台v0\.5\.1"',
        'product_name: str = "WKL-LLM运维平台v0.6"',
        "config product_name",
    ),
    (
        r'product_name_spaced: str = "WKL-LLM运维平台 v0\.5\.1"',
        'product_name_spaced: str = "WKL-LLM运维平台 v0.6"',
        "config product_name_spaced",
    ),
    # ---- 2. 包版本（PEP 440 三段式）----
    (r'^version = "0\.5\.1"$', 'version = "0.6.0"', "pyproject version"),
    (r"^0\.5\.1$", "0.6.0", "VERSION 文件"),
    (r'^version: "0\.5\.1"$', 'version: "0.6.0"', "CITATION version"),
    # ---- 3. 页面版本占位 ----
    (r'<span class="ver">v0\.5\.1</span>', '<span class="ver">v0.6</span>', "页面版本占位"),
    # ---- 4. CI / README 徽章 ----
    (r"version-v0\.5\.1-green", "version-v0.6-green", "徽章版本"),
    (r"badge/version-v0\.5\.1", "badge/version-v0.6", "徽章版本"),
    # ---- 5. 测试断言 ----
    (r's\.product_version == "v0\.5\.1"', 's.product_version == "v0.6"', "测试断言 version"),
    (
        r's\.product_name == "WKL-LLM运维平台v0\.5\.1"',
        's.product_name == "WKL-LLM运维平台v0.6"',
        "测试断言 name",
    ),
    (
        r's\.product_name_spaced == "WKL-LLM运维平台 v0\.5\.1"',
        's.product_name_spaced == "WKL-LLM运维平台 v0.6"',
        "测试断言 spaced",
    ),
    # ---- 6. 文档里的「预期输出」 ----
    (r"`WKL-LLM运维平台v0\.5\.1 v0\.5\.1`", "`WKL-LLM运维平台v0.6 v0.6`", "INSTALL 预期输出"),
    # ---- 7. SECURITY 支持版本表 ----
    (r"\| v0\.5\.x \| ✅ \|", "| v0.6.x | ✅ |", "SECURITY 支持版本"),
    (r"\| < v0\.5 \| ❌ \|", "| < v0.6 | ❌ |", "SECURITY 旧版本"),
    # ---- 8. 验收套件标题里的能力版本范围 ----
    (r"线上能力验收（v0\.4 \+ v0\.4\.3 \+ v0\.5）", "线上能力验收（v0.4 ~ v0.6）", "验收标题"),
    (r"线上能力验收（v0\.4 \+ v0\.4\.3）", "线上能力验收（v0.4 ~ v0.6）", "验收标题"),
    # ---- 9. 探针 docstring 里标注自身版本 ----
    (r"（v0\.5\.1）", "（v0.6）", "探针自身版本标注"),
    (r"^# WKL-LLM运维平台 v0\.5\.1 升级测试报告", "# WKL-LLM运维平台 v0.6 升级测试报告", "报告标题"),
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
        for rx, repl, _why in RULES:
            text, n = re.subn(rx, repl, text, flags=re.M)
            hits += n
        if text != orig:
            changed.append((rel, hits))
            if apply:
                p.write_text(text, encoding="utf-8", newline="\n")

    print(f"=== {'已修改' if apply else '待修改'} {len(changed)} 个文件 ===")
    for rel, n in sorted(changed):
        print(f"  {rel}  ({n} 处)")

    # ---- 剩余命中：逐条列出供人工判定 ----
    print("\n=== 剩余 v0.5 命中（历史标注应保留；下文逐条判定）===")
    residue: list[tuple[str, int, str]] = []
    for p in iter_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in SELF:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(lines, 1):
            if re.search(r"v?0\.5(\.\d)?", ln):
                residue.append((rel, i, ln.strip()[:100]))
    print(f"共 {len(residue)} 处")
    for rel, i, ln in residue[:40]:
        print(f"  {rel}:{i}: {ln}")
    if len(residue) > 40:
        print(f"  … 其余 {len(residue) - 40} 处")

    print(f"\nBUMP_{'APPLIED' if apply else 'DRYRUN'}: 目标版本 v0.6")
    return 0


if __name__ == "__main__":
    sys.exit(main())
