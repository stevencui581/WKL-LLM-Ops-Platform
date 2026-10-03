#!/usr/bin/env python
"""框架徽标诊断（v0.5）。

    cd "$WKL_ROOT" && ./venv/bin/python probes/diag_framework_chip.py

当页面顶部「框架」一直显示"识别中…"时，用本脚本定位是**后端没下发**、
**前端资源过期**，还是**前端渲染报错**。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

B = "http://127.0.0.1:8081"


def get(path: str, timeout: float = 15.0) -> str:
    with urllib.request.urlopen(f"{B}{path}", timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    problems: list[str] = []

    print("=== 1. 后端是否下发 framework ===")
    ov = json.loads(get("/api/overview"))
    fw = ov.get("framework")
    if not fw:
        problems.append("后端 /api/overview 未下发 framework 字段")
        print("  [FAIL] 缺失")
    else:
        print(f"  [OK] id={fw.get('id')} version={fw.get('version')} confidence={fw.get('confidence')}")
        print(f"       capabilities={fw.get('capabilities')}")
        if fw.get("id") in (None, "", "unknown"):
            problems.append(f"后端识别为 unknown（probes={fw.get('probes')}）")

    print("\n=== 2. 页面是否有框架徽标元素 ===")
    html = get("/")
    has_chip = 'id="fwChip"' in html
    has_text = 'id="fwText"' in html
    print(f"  index.html 含 #fwChip: {has_chip}")
    print(f"  index.html 含 #fwText: {has_text}")
    if not has_chip:
        problems.append("index.html 缺少 #fwChip 元素（前端资源过期？）")

    print("\n=== 3. app.js 是否含渲染逻辑且被调用 ===")
    js = get("/app.js")
    defined = "function renderFrameworkChip" in js
    called = re.search(r"renderFrameworkChip\(\s*o\.framework\s*\)", js) is not None
    print(f"  定义 renderFrameworkChip: {defined}")
    print(f"  调用 renderFrameworkChip(o.framework): {called}")
    if not defined:
        problems.append("app.js 缺少 renderFrameworkChip 定义（前端资源过期？）")
    if not called:
        problems.append("app.js 未调用 renderFrameworkChip（前端资源过期？）")

    print("\n=== 4. i18n.js 是否含占位词条与 lang 字段 ===")
    i18n = get("/i18n.js")
    has_key = "'top.fw_detecting'" in i18n
    has_global = "global.I18N = {" in i18n or "global.I18N=" in i18n
    has_lang = re.search(r"\blang:\s*LANG", i18n) is not None
    print(f"  含 'top.fw_detecting': {has_key}")
    print(f"  导出 global.I18N: {has_global}")
    print(f"  I18N.lang 存在: {has_lang}")
    if not has_key:
        problems.append("i18n.js 缺少 top.fw_detecting 词条")
    if not has_lang:
        problems.append("I18N.lang 不存在 —— renderFrameworkChip 里的 pick() 会拿到 undefined")

    print("\n=== 5. 模拟前端取值（用真实接口数据）===")
    if fw:
        for lang in ("zh", "en"):
            pickd = (fw.get("name") or {}).get(lang)
            print(f"  name[{lang}] = {pickd!r}")
            if not pickd:
                problems.append(f"framework.name.{lang} 缺失 —— 该语言下会回退到 id")
        print(f"  最终显示应为: {pickd}" if fw.get("name") else "  name 缺失")

    print()
    if problems:
        print(f"DIAG_FRAMEWORK_FAILED: {len(problems)} 项")
        for p in problems:
            print("  -", p)
        return 1
    print("DIAG_FRAMEWORK_OK: 后端与前端资源均正常")
    print("  如果浏览器仍显示「识别中…」，请强制刷新（Ctrl+Shift+R）清除旧 app.js 缓存。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
