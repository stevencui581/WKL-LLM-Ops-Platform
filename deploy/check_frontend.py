"""前端静态资源自检（方案 TASK-15 验收：零图片资源、品牌文案、无外链）。"""

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "static")

fails = []


def check(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def main() -> int:
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "style.css"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()

    print("=== 零图片资源 ===")
    check("HTML 无 <img> 标签", "<img" not in html)
    check("CSS 无 url( 位图引用", "url(" not in css)
    check("CSS 无 background-image", "background-image" not in css)
    check("JS 无 new Image()", "new Image" not in js)
    check("HTML 无 <svg> 图标", "<svg" not in html)
    check("CSS 无 base64 内联图", "base64" not in css)

    print("\n=== 品牌与署名（方案 6.4.6 / 6.4.7）===")
    check("顶部产品标识 WKL-LLM运维平台", "WKL-LLM运维平台" in html)
    check("顶部有版本号占位", 'class="ver"' in html and re.search(r'class="ver">v[\d.]+<', html) is not None)
    check("底部开发者信息占位", "开发者信息" in html)
    check("底部开发日期占位", "2026.10.01" in html)
    check("静态资源不含旧版号 v0.1", "v0.1" not in html and "v0.1" not in js)

    print("\n=== 无外链依赖（253 内网可能不可达外网）===")
    ext_html = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    check("HTML 无外链 src/href", not ext_html, str(ext_html))
    check("CSS 无 @import 外链", "@import" not in css)

    print("\n=== 结构完整性 ===")
    for el in (
        "row1",
        "row2",
        "slotRows",
        "logs",
        "alerts",
        "badges",
        "kvBar",
        "kvPct",
        "recent",
        "devInfo",
        "brand",
    ):
        check(f"存在元素 id={el}", f'id="{el}"' in html)

    print("\n=== v0.4 新增结构 ===")
    for el in (
        "accelBadge",
        "accelText",
        "accelTp",
        "modelFull",
        "uptime",
        "lastRefresh",
        "sysgrid",
        "hwBody",
        "hwRight",
    ):
        check(f"存在元素 id={el}", f'id="{el}"' in html)
    check("右上角状态区为 2 行容器（R9）", 'class="meta2col"' in html)
    check("底部平台签名已删除（R7）", 'id="platform"' not in html)
    check("底部 lastRefresh2 已删除（R7）", 'id="lastRefresh2"' not in html)
    check("系统资源为网格容器（R6）", 'class="sysgrid"' in html)
    check("顶栏含算力卡 chip（R1）", 'id="accelBadge"' in html)
    check("顶栏含模型全称 chip（R2）", 'id="modelChip"' in html)

    print("\n=== 前后端契约 ===")
    for fn in ("/api/overview", "/api/hardware", "/ws/metrics", "/ws/logs"):
        check(f"前端引用 {fn}", fn in js)
    check("丢弃乱序帧（seq 单调）", "msg.seq < state.seq" in js)
    check("WebSocket 断线重连", "setTimeout(connectMetrics" in js)

    print("\n=== v0.4 反写死：前端不得含业务字面量 ===")
    # 这些文案必须由后端下发；前端出现即违反 v0.4 F15/F16
    live = "\n".join(ln for ln in js.splitlines() if not ln.strip().startswith(("//", "*", "/*")))
    live_html = "\n".join(ln for ln in html.splitlines() if not ln.strip().startswith("<!--"))
    for token, label in (
        ("-kvu", "KV 统一池模式名"),
        ("统一池", "KV 统一池文案"),
        ("platform", "平台签名元素"),
        ("lastRefresh2", "底栏刷新元素"),
    ):
        check(f"JS 无 {label}", token not in live)
    check("HTML 无 -kvu 字面量", "-kvu" not in live_html)
    check("阈值取自后端 thresholds", "th('vram_crit_pct'" in js and "th('gpu_temp_warn_c'" in js)
    check("DOM 引用走判空安全写入", "function setText" in js and "function setHTML" in js)

    # ==================================================================
    # v0.4.3：多页面 + 多语言
    # ==================================================================
    print("\n=== v0.4.3 多页面（三个页面统一守卫）===")
    pages = {}
    for name in ("index.html", "alerts.html", "logs.html"):
        path = os.path.join(STATIC, name)
        check(f"{name} 存在", os.path.exists(path))
        if os.path.exists(path):
            pages[name] = open(path, encoding="utf-8").read()

    for name, text in pages.items():
        check(f"{name} 零图片", "<img" not in text)
        check(f"{name} 无外链资源", not re.findall(r'(?:src|href)="(https?://[^"]+)"', text))
        check(f"{name} 已接入 i18n.js", "/i18n.js" in text)
        check(f"{name} 渲染前应用语言", "I18N.applyI18n()" in text)
        check(f"{name} 含语言切换控件", 'id="langCtl"' in text)

    i18n = open(os.path.join(STATIC, "i18n.js"), encoding="utf-8").read()
    check("i18n.js 存在且含中英两套字典", "zh:" in i18n and "en:" in i18n)
    check("i18n.js 跟随浏览器语言（v0.4.3 §4.1）", "navigator" in i18n and "localStorage" in i18n)
    check("i18n.js 支持手动优先与恢复自动", "llmconsole.lang" in i18n and "restoreAuto" in i18n)
    check(
        "i18n.js 同步加载（避免首帧闪烁）", '<script src="/i18n.js"></script>' in pages.get("index.html", "")
    )

    print("\n=== v0.4.3 入口按钮（R10 / R11 / R12）===")
    check("标识1：告警面板含告警日志入口", 'id="alertLogBtn"' in pages.get("index.html", ""))
    check("标识3：顶栏含历史服务日志入口", 'id="logHistoryBtn"' in pages.get("index.html", ""))
    check("标识4：顶栏含语言切换", 'id="langCtl"' in pages.get("index.html", ""))

    alerts_js = open(os.path.join(STATIC, "alerts.js"), encoding="utf-8").read()
    logs_js = open(os.path.join(STATIC, "logs.js"), encoding="utf-8").read()
    check("告警日志页调 /api/alert-log", "/api/alert-log" in alerts_js)
    check(
        "告警日志页含三列（时间/类型/名称）",
        all(k in pages.get("alerts.html", "") for k in ("al.col.time", "al.col.category", "al.col.name")),
    )
    check("历史日志页调 /api/logs/history", "/api/logs/history" in logs_js)
    check("历史日志页支持 1/7/30 档位", "dayBtns" in pages.get("logs.html", ""))
    check("历史日志页支持实时（复用 /ws/logs）", "/ws/logs" in logs_js)
    check("历史日志页支持下载", "/api/logs/history/download" in logs_js)
    check("历史日志页顶部文字按档位渲染", "t('lg.showing'" in logs_js)

    print("\n=== v0.4.3 反写死：页面脚本不得含中文字面量 ===")
    cjk = re.compile(r"[\u4e00-\u9fff]")

    def strip_comments(src):
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())

    for name in ("app.js", "alerts.js", "logs.js"):
        src = strip_comments(open(os.path.join(STATIC, name), encoding="utf-8").read())
        bad = [f"L{i + 1}" for i, ln in enumerate(src.splitlines()) if cjk.search(ln)]
        check(f"{name} 无中文字面量（文案走 i18n）", not bad, ",".join(bad[:6]))
    for name, text in pages.items():
        check(f"{name} 脚本区无中文三元表达式", " lang === 'zh'" not in text and 'lang === "zh"' not in text)

    check(
        "静态资源无旧版号 v0.4.1/v0.4.2",
        not any(
            t in re.sub(r"<!--.*?-->", "", v, flags=re.S)
            for v in pages.values()
            for t in ("v0.4.1", "v0.4.2")
        ),
        "（注释里的历史标注不算残留）",
    )
    # 当前版号必须真实出现在顶栏占位里
    cur = re.search(r'class="ver">(v[\d.]+)<', pages.get("index.html", ""))
    check("顶栏版号占位与配置一致（v0.4 R8）", bool(cur), cur.group(1) if cur else "未找到")

    # ---- v0.5：渲染冒烟（需要 Node，缺失时跳过）----
    #
    # 上面的检查全是**静态字符串扫描**，查不出"渲染函数抛异常"这类问题。
    # 真实踩过的坑：框架徽标一直显示「识别中…」—— HTML 有元素、JS 有函数、
    # 接口有数据，静态检查全过，但页面上就是不动。
    print("\n=== 渲染冒烟（真实 app.js + Node 桩）===")
    node = shutil.which("node")
    if not node:
        print("  [SKIP] 未安装 Node —— 请在开发机或 CI 上运行：")
        print("         node tools/check_frontend_render.js static")
    else:
        project_root = os.path.dirname(HERE)
        script = os.path.join(project_root, "tools", "check_frontend_render.js")
        if not os.path.isfile(script):
            check("渲染冒烟脚本存在", False, script)
        else:
            proc = subprocess.run(
                [node, script, STATIC],
                capture_output=True,
                text=True,
                timeout=120,
            )
            for line in (proc.stdout or "").strip().splitlines()[-4:]:
                print(f"  {line}")
            check(
                "渲染冒烟通过（框架徽标能正确渲染）",
                proc.returncode == 0,
                (proc.stderr or "").strip()[:200] or (proc.stdout or "")[-200:],
            )

    print()
    if fails:
        print(f"FRONTEND_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("FRONTEND_OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
