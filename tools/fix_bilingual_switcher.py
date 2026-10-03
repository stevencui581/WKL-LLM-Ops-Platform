"""给缺失的中文文档补上指向英文版的切换链接（v0.5.1 一次性工具）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAIRS = [
    "README",
    "CHANGELOG",
    "CONTRIBUTING",
    "CODE_OF_CONDUCT",
    "SECURITY",
    "AGENTS",
    "docs/README",
    "docs/INSTALL",
    "docs/ARCHITECTURE",
    "docs/CONFIGURATION",
    "docs/API",
    "docs/FAQ",
    "docs/TROUBLESHOOTING",
]

#: 中文版标题 → 英文版相对链接与显示名
TITLES = {
    "README": "项目主页",
    "CHANGELOG": "更新日志",
    "CONTRIBUTING": "贡献指南",
    "CODE_OF_CONDUCT": "行为准则",
    "SECURITY": "安全策略",
    "AGENTS": "AI 助手约定",
    "docs/README": "文档索引",
    "docs/INSTALL": "安装说明",
    "docs/ARCHITECTURE": "架构设计",
    "docs/CONFIGURATION": "配置参考",
    "docs/API": "API 文档",
    "docs/FAQ": "常见问题",
    "docs/TROUBLESHOOTING": "故障排查",
}


def main() -> int:
    apply = "--apply" in sys.argv
    fixed = 0
    for base in PAIRS:
        stem = Path(base).name
        zh = ROOT / f"{base}.zh-CN.md"
        en = ROOT / f"{base}.md"
        if not zh.is_file() or not en.is_file():
            print(f"  [跳过] {zh.name} 或英文版缺失")
            continue
        lines = zh.read_text(encoding="utf-8").splitlines()
        target = f"{stem}.md"  # 同目录下的英文版
        # 前 6 行里是否已有指向自己的英文版链接
        head = "\n".join(lines[:6])
        if target in head and ".zh-CN.md" not in head.split(target)[0][-30:]:
            continue
        # 检查是否已有形如 [English](X.md) 且 X 就是本文件
        if re.search(rf"\[English\]\({re.escape(target)}\)", head):
            continue
        switcher = f"[English]({target}) · **中文**"
        # 插到标题后（若有副标题行则再往后）
        idx = 1
        if len(lines) > 1 and lines[1].strip():
            idx = 1
        lines.insert(idx, "")
        lines.insert(idx + 1, switcher)
        print(f"  {'补切换链接' if apply else '待补'} {zh.relative_to(ROOT)} -> {switcher}")
        if apply:
            zh.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        fixed += 1
    print(f"\nBILINGUAL_SWITCHER_{'APPLIED' if apply else 'DRYRUN'}: {fixed} 份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
