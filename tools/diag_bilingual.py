"""诊断双语文档一致性（临时工具）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]")
FENCE = "`" * 3

PAIRS = [
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/INSTALL.md",
    "docs/ARCHITECTURE.md",
    "docs/CONFIGURATION.md",
    "docs/API.md",
    "docs/FAQ.md",
    "docs/TROUBLESHOOTING.md",
]


def zh_of(rel: str) -> Path:
    p = ROOT / rel
    return p.with_name(p.stem + ".zh-CN.md")


def heads(text: str) -> list[int]:
    out: list[int] = []
    in_fence = False
    for ln in text.splitlines():
        s = ln.rstrip()
        if s.startswith(FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+\S", s)
        if m:
            out.append(len(m.group(1)))
    return out


def count(text: str, pred) -> int:
    return sum(1 for ln in text.splitlines() if pred(ln))


def main() -> int:
    print("=== 英文文档里的中文行 ===")
    for rel in PAIRS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        hits = [(i, ln.strip()) for i, ln in enumerate(text.splitlines(), 1) if CJK.search(ln)]
        if hits:
            print(f"  {rel}: {len(hits)} 行")
            for i, ln in hits[:6]:
                print(f"     {i}: {ln[:110]}")

    print("\n=== 结构对等 ===")
    for rel in PAIRS:
        en = (ROOT / rel).read_text(encoding="utf-8")
        zh = zh_of(rel).read_text(encoding="utf-8")
        eh, zh_h = heads(en), heads(zh)
        ef = count(en, lambda x: x.strip().startswith(FENCE))
        zf = count(zh, lambda x: x.strip().startswith(FENCE))
        et = count(en, lambda x: x.strip().startswith("|"))
        zt = count(zh, lambda x: x.strip().startswith("|"))
        flag = "OK " if (eh == zh_h and ef == zf and et == zt) else "差异"
        if flag != "OK ":
            print(
                f"  [{flag}] {rel}: 标题 EN{len(eh)}/ZH{len(zh_h)} 代码块 EN{ef}/ZH{zf} 表格行 EN{et}/ZH{zt}"
            )
            if eh != zh_h:
                print(f"         EN={eh}")
                print(f"         ZH={zh_h}")

    print("\n=== 中文版是否含指向英文版的链接 ===")
    for rel in PAIRS:
        zh = zh_of(rel)
        text = zh.read_text(encoding="utf-8")
        ok = ".md)" in text and ".zh-CN.md" not in text.split("\n")[2] if len(text.split("\n")) > 2 else False
        has_en_link = bool(re.search(r"\]\((?!\S*\.zh-CN\.md)[^)]+\.md\)", text))
        if not has_en_link:
            print(f"  [缺] {zh.name} 前 5 行：")
            for ln in text.splitlines()[:5]:
                print(f"        {ln[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
