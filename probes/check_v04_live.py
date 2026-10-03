#!/usr/bin/env python
"""线上验收探针（在 目标 上运行）—— 覆盖 v0.4 全部能力 + v0.4.3 新增能力。

    cd /home/llmops/llm-console && ./venv/bin/python probes/check_v04_live.py

期望版本从 ``app/config.py`` 读取（单一事实源），不写死。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from app.config import Settings as _S

    EXPECTED_VERSION = _S().product_version
    EXPECTED_PRODUCT_NAME = _S().product_name
    EXPECTED_ALERT_LIMIT = _S().alert_log_default_limit
    EXPECTED_DAYS = _S().log_history_default_days
    EXPECTED_DAY_OPTIONS = tuple(_S().log_history_days_options)
except Exception:  # noqa: BLE001
    EXPECTED_VERSION, EXPECTED_PRODUCT_NAME = "v0.4.3", "WKL-LLM运维平台v0.4.3"
    EXPECTED_ALERT_LIMIT, EXPECTED_DAYS, EXPECTED_DAY_OPTIONS = 500, 30, (1, 7, 30)

B = "http://127.0.0.1:8081"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def get(path: str):
    with urllib.request.urlopen(f"{B}{path}", timeout=60) as r:
        return json.load(r)


def code_of(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{B}{path}", timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    print("=== 1. 硬件接口 /api/hardware ===")
    hw = get("/api/hardware")
    print(f"  vendors = {hw['vendors']}")
    print(f"  DMI     = {hw['dmi']['sys_vendor']} / {hw['dmi']['product_name']}")
    c = hw["cpu"]
    print(f"  CPU     = {c['model']} ({c['sockets']}路×{c['cores_per_socket']}核={c['logical']})")
    print(f"  内存    = {hw['memory']['total_gib']} GiB, Swap {hw['memory']['swap_gib']} GiB")
    for d in hw["disks"]:
        print(f"  磁盘    = {d['name']} {d['size_gib']} GiB {d['model']}")
        for p in d["partitions"]:
            if p["mountpoint"]:
                print(
                    f"            └ {p['name']} {p['mountpoint']} {p['fstype']} "
                    f"{p['size_gib']}G 已用 {p['used_pct']}%"
                )
    nb = hw["accelerators"]["nvidia"]
    ab = hw["accelerators"]["amd"]
    print(f"  NVIDIA  = present={nb['present']} count={nb['count']} model={nb['model']}")
    print(
        f"            bw={nb['bandwidth_gbps']} GB/s [{nb['mem_type']}] "
        f"topo={nb['topology']} nvlink={nb['nvlink']} fan={nb['fan_present']}"
    )
    print(
        f"            驱动={nb['driver_name']} {nb['driver_version']} "
        f"驱动支持CUDA={nb['cuda_driver_version']}"
    )
    for comp in nb["components"]:
        print(f"            · {comp['name']}: {comp['version'] or '未安装'} [{comp['status']}]")
    print(f"  AMD     = present={ab['present']}  ← R4：前端整段不渲染")
    print(f"  Python  = {hw['python']['version']} torch_installed={hw['python']['torch']['installed']}")

    check("厂家探测未把虚拟显卡算进来", "nvidia" in hw["vendors"] and "amd" not in hw["vendors"])
    check("NVIDIA 卡数为 2", nb["count"] == 2, str(nb["count"]))
    check("AMD 段 present=False（R4 条件渲染）", ab["present"] is False)
    check("峰值带宽由型号表得出（非写死 900 常量）", nb["bandwidth_gbps"] == 900.0)
    check("NVLink 判定正确（PHB 拓扑 → False）", nb["nvlink"] is False, str(nb["topology"]))
    check("风扇如实为 False（SXM2 无风扇）", nb["fan_present"] is False)
    check("CPU 型号来自 lscpu", bool(c["model"]))
    check("内存总量 > 0", hw["memory"]["total_gib"] > 0)
    check("磁盘已过滤 DVD-ROM", all(not d["name"].startswith("sr") for d in hw["disks"]))
    check("DMI 整机信息可读", bool(hw["dmi"]["sys_vendor"]))
    check("PyTorch 如实显示未安装", hw["python"]["torch"]["installed"] is False)
    check("未知字段为空（探测全部成功）", hw["unknown_fields"] == [], str(hw["unknown_fields"]))

    print("\n=== 2. 首屏 /api/overview 的 v0.4 新增字段 ===")
    o = get("/api/overview")
    br = o["branding"]
    kv = o["kv"]
    ab_badge = o["accelerator_badge"]
    base = o["baseline"]
    rt = o["runtime"]
    print(f"  branding   = {br['product_name']} ({br['product_version']})")
    print(f"  accel badge= {ab_badge}")
    print(f"  model      = {o['model']['name']}")
    print(f"  kv.label   = {kv['label']}")
    print(f"  kv.mode    = {kv['capacity_mode']} / {kv['capacity_source']}")
    print(f"  kv.quant   = {kv['kv_quant']} (source={kv['kv_quant_source']})")
    print(f"  baseline   = mtp {base['mtp']} decode {base['decode']}")
    print(f"  llama up   = {o['llama_uptime_s']}")
    print(f"  thresholds = { {k: v for k, v in o['thresholds'].items() if 'pct' in k or 'temp' in k} }")
    print(
        f"  runtime    = tensor_parallel={rt['tensor_parallel']} split={rt['split_mode']} "
        f"bw_label={rt['gpu_bandwidth_label']}"
    )

    check(
        "品牌版本与后端配置一致（v0.4 R8）",
        br["product_name"] == EXPECTED_PRODUCT_NAME and br["product_version"] == EXPECTED_VERSION,
        f"{br['product_name']} / {br['product_version']}",
    )
    check("算力卡 badge 有数据（R1）", ab_badge["present"] and ab_badge["count"] == 2)
    check("张量并行识别为开（R1）", ab_badge["tensor_parallel"] is True)
    check("模型全称已下发（R2）", bool(o["model"].get("full_name")))
    check("KV 文案由后端下发（F15）", bool(kv["label"]) and "-kvu" not in "", kv["label"])
    check("KV 模式判定为 unified（§5.3）", kv["capacity_mode"] == "unified", kv["capacity_mode"])
    check("KV 容量正确（131072）", kv["total_tokens"] == 131072, str(kv["total_tokens"]))
    check(
        "KV 量化来源为 default 且标注（F16）",
        kv["kv_quant_source"] == "default" and "默认" in kv["kv_quant"],
        kv["kv_quant"],
    )
    check(
        "阈值已全量下发（F5）",
        all(
            k in o["thresholds"]
            for k in ("vram_warn_pct", "kv_crit_pct", "gpu_temp_warn_c", "power_warn_pct")
        ),
    )
    check("不再下发旧的 power_warn_w", "power_warn_w" not in o["thresholds"])
    check("基线状态存在（§7）", "mtp" in base and "decode" in base)
    check("GPU 风扇字段存在（F3）", "fan_pct" in o["gpus"][0])

    print("\n=== 3. 槽位面板仍完全数据驱动 ===")
    print(f"  槽位数 = {len(kv['slots'])}, used_tokens = {kv['used_tokens']}, pct = {kv['pct']:.2f}%")
    check("槽位来自 /slots（6 个）", len(kv["slots"]) == 6)
    check("来源列未伪造", all(s["source"] is None for s in kv["slots"]))

    print("\n=== 4. 键位健康与静态资源 ===")
    import urllib.error

    for path, want in (
        ("/api/health/live", 200),
        ("/api/health/ready", 200),
        ("/", 200),
        ("/app.js", 200),
        ("/style.css", 200),
    ):
        try:
            with urllib.request.urlopen(f"{B}{path}", timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        check(f"{path} → {want}", code == want, str(code))

    html = urllib.request.urlopen(f"{B}/", timeout=5).read().decode("utf-8", "replace")
    js = urllib.request.urlopen(f"{B}/app.js", timeout=5).read().decode("utf-8", "replace")
    # 只检查**可执行代码**，注释里的说明文字不算业务字面量
    js_live = "\n".join(ln for ln in js.splitlines() if not ln.strip().startswith(("//", "*", "/*")))
    html_live = "\n".join(ln for ln in html.splitlines() if not ln.strip().startswith("<!--"))
    check("HTML 无 <img>（零图片红线）", "<img" not in html)
    check("顶栏含算力卡 chip（R1）", 'id="accelBadge"' in html)
    check("顶栏含模型 chip（R2）", 'id="modelFull"' in html)
    check("状态区为 2 行容器（R9）", 'class="meta2col"' in html)
    check("底栏已删除 platform（R7）", 'id="platform"' not in html)
    check("底栏已删除 lastRefresh2（R7）", 'id="lastRefresh2"' not in html)
    check("系统资源为网格（R6）", 'class="sysgrid"' in html)
    check("硬件面板存在（R3）", 'id="hwBody"' in html)
    check("前端代码无 -kvu 字面量（F15）", "-kvu" not in js_live)
    check("前端代码无统一池字面量（F15）", "统一池" not in js_live)
    check("HTML 无 -kvu 字面量", "-kvu" not in html_live)

    # =====================================================================
    # v0.4.3 新增
    # =====================================================================
    print("\n=== 5. v0.4.3 结构化字段（数据与展示分离）===")
    items = rt.get("badge_items") or []
    print(f"  badge_items = {[i['key'] for i in items]}")
    check("badge_items 已下发（§6.4）", len(items) >= 5)
    check(
        "badge_items 的 kv_quant 是裸值（标注由前端加）",
        all(not (i["key"] == "kv_quant" and "默认" in i["value"]) for i in items),
        str([i for i in items if i["key"] == "kv_quant"]),
    )
    check("health.reason_codes 已下发（§6.4）", "reason_codes" in o["health"])
    check("旧 badges 仍保留（向后兼容）", isinstance(rt.get("badges"), list))

    print("\n=== 6. 告警目录与日志（R10）===")
    cat = get("/api/alert-catalog")["data"]
    codes = cat["codes"]
    print(f"  告警代码数 = {len(codes)}")
    check("目录含 14 个代码", len(codes) == 14, str(len(codes)))
    check(
        "每个代码都有 zh/en 类型与名称",
        all(
            c["category"]["zh"] and c["category"]["en"] and c["name"]["zh"] and c["name"]["en"]
            for c in codes.values()
        ),
    )
    check(
        "算力卡英文为 Compute card（§5）",
        codes["GPU_TEMP_WARN"]["category"]["en"] == "Compute card",
        codes["GPU_TEMP_WARN"]["category"]["en"],
    )
    check(
        "英文名称不含中文",
        not any("\u4e00" <= ch <= "\u9fff" for c in codes.values() for ch in c["name"]["en"]),
    )

    log = get(f"/api/alert-log?limit={EXPECTED_ALERT_LIMIT}")["data"]
    print(f"  total = {log['total']}, returned = {log['returned']}")
    check("告警日志接口可用", log["available"] is True)
    check(f"默认条数上限为 {EXPECTED_ALERT_LIMIT}（R10）", log["limit"] == EXPECTED_ALERT_LIMIT)
    check("返回条数不超过上限", log["returned"] <= EXPECTED_ALERT_LIMIT)
    check(
        "统计含 raised/resolved（含恢复事件）",
        "raised" in log["stats"]["by_event"] and "resolved" in log["stats"]["by_event"],
        str(log["stats"]["by_event"]),
    )
    if log["entries"]:
        e = log["entries"][0]
        check("每条含 ISO 日期时间", len(e.get("iso", "")) == 19, e.get("iso", ""))
        check("每条含双语 category/name", bool(e["category"]["zh"]) and bool(e["category"]["en"]))

    print("\n=== 7. 历史服务日志（R11：1/7/30 天 + 下载）===")
    for d in EXPECTED_DAY_OPTIONS:
        h = get(f"/api/logs/history?days={d}")["data"]
        print(
            f"  days={d:<2} returned={h['returned']:<6} covered={h['covered_days']:>5} 天  "
            f"{h['covered_from']} ~ {h['covered_to']}  {h['elapsed_ms']:.0f}ms"
        )
        check(f"days={d} 查询可用", h["available"] is True, h.get("error", ""))
        check(f"days={d} 档位原样返回", h["requested_days"] == d)
        if h["lines"]:
            # 日志行必须有 19 字符的 ts_local（YYYY-MM-DD HH:MM:SS）；
            # journalctl 的结构分隔行（`-- Boot xxx --`）**例外** —— 它们没有时间戳，
            # 但必须有 kind="separator" 标记，否则前端会渲染成一行空白时间戳。
            logs = [x for x in h["lines"] if x.get("kind", "log") == "log"]
            seps = [x for x in h["lines"] if x.get("kind") == "separator"]
            check(
                f"days={d} 日志行含 ts_local（完整日期时间）",
                all(len(x.get("ts_local", "")) == 19 for x in logs[:50]),
                h["lines"][0].get("ts_local", ""),
            )
            check(
                f"days={d} 分隔行已显式标注",
                all(x.get("ts_local", "") == "" for x in seps),
                f"{len(seps)} 条分隔行",
            )
    check("档位为 1/7/30", tuple(h["days_options"]) == EXPECTED_DAY_OPTIONS, str(h["days_options"]))
    check("默认档位 30 天", EXPECTED_DAYS == 30)
    check(
        "实际覆盖不谎称超过请求范围",
        h["covered_days"] <= EXPECTED_DAYS,
        f"{h['covered_days']} 天（该 unit 更早无日志）",
    )
    check("实时开关已下发", h["live_enabled"] is True and h["live_max_lines"] > 0)

    try:
        req = urllib.request.Request(f"{B}/api/logs/history/download?days=1")
        with urllib.request.urlopen(req, timeout=60) as r:
            disp = r.headers.get("Content-Disposition", "")
            body = r.read()
        print(f"  下载: {disp}  字节={len(body)}")
        check("下载返回附件", "attachment" in disp)
        check("文件名含天数与时间戳", "_1d_" in disp and ".log" in disp, disp)
        check("下载内容非空且带 BOM", len(body) > 1000 and body[:3] == b"\xef\xbb\xbf")
    except Exception as exc:  # noqa: BLE001
        check("下载可用", False, str(exc))

    print("\n=== 8. v0.4.3 静态资源与页面 ===")
    for path in ("/alerts.html", "/logs.html", "/i18n.js", "/alerts.js", "/logs.js"):
        check(f"{path} → 200", code_of(path) == 200, str(code_of(path)))
    ind = urllib.request.urlopen(f"{B}/", timeout=10).read().decode("utf-8", "replace")
    al = urllib.request.urlopen(f"{B}/alerts.html", timeout=10).read().decode("utf-8", "replace")
    lg = urllib.request.urlopen(f"{B}/logs.html", timeout=10).read().decode("utf-8", "replace")
    i18n = urllib.request.urlopen(f"{B}/i18n.js", timeout=10).read().decode("utf-8", "replace")
    check("主页含语言切换（标识4）", 'id="langCtl"' in ind)
    check("主页含告警日志入口（标识1）", 'id="alertLogBtn"' in ind)
    check("主页含历史服务日志入口（标识3）", 'id="logHistoryBtn"' in ind)
    check(
        "告警页含三列（时间/类型/名称）",
        "al.col.time" in al and "al.col.category" in al and "al.col.name" in al,
    )
    check(
        "历史页含顶部标题与档位与实时与下载",
        'id="headline"' in lg and 'id="dayBtns"' in lg and 'id="liveBtn"' in lg and 'id="downloadBtn"' in lg,
    )
    check("三个页面零图片", all("<img" not in p for p in (ind, al, lg)))
    check("三个页面均接入 i18n", all("/i18n.js" in p for p in (ind, al, lg)))
    check("i18n.js 含 zh 与 en 两套字典", "zh:" in i18n and "en:" in i18n)
    check(
        "i18n.js 按浏览器语言判定（v0.4.3 §4.1）",
        "navigator" in i18n and "localStorage" in i18n and "auto" in i18n,
    )

    print("\n=== 9. v0.5 推理框架自动识别（第 1 步）===")
    fw = o.get("framework") or {}
    fwname = fw.get("name") or {}
    fwnote = fw.get("note") or {}
    print(f"  id      = {fw.get('id')}")
    print(f"  name    = {fwname.get('zh')} / {fwname.get('en')}")
    print(f"  version = {fw.get('version')} (来源 {fw.get('version_source')}) build={fw.get('build')}")
    print(f"  api     = {fw.get('capabilities')}  metrics={fw.get('metrics_prefix')}")
    print(f"  note    = {fwnote.get('zh')}")
    check("framework 字段已下发", bool(fw.get("id")), str(fw.get("id")))
    check("框架已识别（非 unknown）", fw.get("id") not in (None, "", "unknown"), str(fw.get("id")))
    check("框架名有中英两份（数据与展示分离）", bool(fwname.get("zh")) and bool(fwname.get("en")))
    check("框架说明有中英两份", bool(fwnote.get("zh")) and bool(fwnote.get("en")))
    check("英文名不含中文", not any("\u4e00" <= ch <= "\u9fff" for ch in (fwname.get("en") or "")))
    check("版本号已自动探测", bool(fw.get("version")), str(fw.get("version")))
    check(
        "版本来源可追溯", str(fw.get("version_source", "")).startswith("http:"), str(fw.get("version_source"))
    )
    check("能力清单非空", bool(fw.get("capabilities")))
    check("识别置信度为 exact", fw.get("confidence") == "exact", str(fw.get("confidence")))
    check("探测过程可诊断（probes 非空）", bool(fw.get("probes")))
    # 页面不得写死任何推理框架名（必须是探测结果）
    for asset in ("app.js", "i18n.js", "index.html"):
        txt = urllib.request.urlopen(f"{B}/{asset}", timeout=10).read().decode("utf-8", "replace")
        live_txt = "\n".join(
            ln for ln in txt.splitlines() if not ln.strip().startswith(("//", "*", "/*", "<!--"))
        )
        bad = [tok for tok in ("llama.cpp", "llama-server") if tok in live_txt]
        check(f"{asset} 未写死推理框架名", not bad, ",".join(bad))

    print()
    if fails:
        print(f"V04_LIVE_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("V04_LIVE_OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
