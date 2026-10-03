#!/usr/bin/env python
"""品牌一致性核对（v0.5）。

    cd "$WKL_ROOT" && ./venv/bin/python probes/check_branding.py

校验的是**一致性**，而不是某个特定名字：

  1. 后端配置（单一事实源）里有品牌与版本
  2. 运行期接口下发的品牌与后端配置**完全相同**
  3. 三个页面都显示了品牌与版本占位
  4. 前端脚本里**没有写死版本号**（升版只需改 config.py 一处）
  5. 英文品牌名里不含中文

为什么这样设计
    早期版本把"不得出现旧品牌"写死在脚本里 —— 那样脚本自身就带着旧品牌字符串，
    开源发布时必须把它一起删掉，等于丢掉一个守卫。
    改为**校验一致性**后，脚本对任何品牌名都成立，二次开发改名也照样能用。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

B = "http://127.0.0.1:8081"
PAGES = ("/", "/alerts.html", "/logs.html")
SCRIPTS = ("/app.js", "/i18n.js", "/alerts.js", "/logs.js")
VER_LITERAL = re.compile(r"['\"]v\d+\.\d+")

fails: list[str] = []
passes: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (passes if cond else fails).append(f"{name}{(' — ' + detail) if detail else ''}")


def get(path: str, timeout: float = 15.0) -> str:
    with urllib.request.urlopen(f"{B}{path}", timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    from app.config import Settings

    s = Settings()
    print("=== 后端配置（单一事实源）===")
    print(f"  product_name        = {s.product_name}")
    print(f"  product_name_spaced = {s.product_name_spaced}")
    print(f"  product_version     = {s.product_version}")
    print(f"  developer           = {s.developer}")

    check("后端配置有品牌名", bool(s.product_name.strip()))
    check("后端配置有版本号", bool(s.product_version.strip()))
    check("后端配置有开发者信息", bool(s.developer.strip()))

    print("\n=== 运行期接口 ===")
    b = json.loads(get("/api/overview"))["branding"]
    for k in ("product_name", "product_name_spaced", "product_version", "developer"):
        print(f"  {k:20} = {b[k]}")
        check(f"接口 {k} 与后端配置一致", b[k] == getattr(s, k), f"{b[k]!r} vs {getattr(s, k)!r}")

    print("\n=== 页面 ===")
    for page in PAGES:
        txt = get(page)
        check(f"{page} 含品牌标识", 'class="brand"' in txt)
        check(f"{page} 含版本占位", 'class="ver"' in txt)
        check(f"{page} 无 <img> 标签（零图片）", "<img" not in txt)

    print("\n=== 前端脚本 ===")
    i18n = get("/i18n.js")
    check("i18n.js 含品牌词条", "'app.brand'" in i18n and "'app.title'" in i18n)
    check("i18n.js 含 en 字典", "'app.title':" in i18n and "DICT" in i18n)

    for asset in SCRIPTS:
        try:
            txt = get(asset)
        except Exception:  # noqa: BLE001 - 部分页面脚本在旧版本可能不存在
            continue
        # 去掉注释再查：注释里的版本号是正常的历史说明
        code = "\n".join(
            ln.split("//", 1)[0] for ln in txt.splitlines() if not ln.strip().startswith(("*", "/*"))
        )
        m = VER_LITERAL.search(code)
        check(f"{asset} 未写死版本号", m is None, m.group(0) if m else "")

    # 英文品牌名里不应有中文
    m = re.search(r"'app\.title':\s*'([^']*)'", i18n)
    if m:
        en_title = m.group(1)
        check("英文品牌名不含中文", not any("\u4e00" <= ch <= "\u9fff" for ch in en_title), en_title)

    print()
    for p in passes:
        print(f"  [PASS] {p}")
    if fails:
        print()
        print(f"BRANDING_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print(f"\nBRANDING_OK: 全部通过（{len(passes)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
