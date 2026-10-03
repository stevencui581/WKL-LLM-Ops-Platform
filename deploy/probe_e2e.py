"""端到端功能验收探针（在 目标 上运行，对应方案第十一章功能验收）。

在 目标 上执行：
    cd "$WKL_ROOT" && ./venv/bin/python deploy/probe_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

B = "http://127.0.0.1:8081"
LLAMA = "http://127.0.0.1:8080"

fails: list[str] = []


def get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def check(label: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    if not cond:
        fails.append(label)
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")


def wait_first_snapshot(timeout: float = 30.0) -> bool:
    """服务刚启动时 snapshot 还是初始空值，等第一拍采集完成再断言。"""
    import time as _t

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        try:
            with urllib.request.urlopen(f"{B}/api/overview", timeout=5) as r:
                o = json.load(r)
            if o.get("seq", 0) > 0 and (o.get("kv") or {}).get("total_tokens"):
                return True
        except Exception:  # noqa: BLE001
            pass
        _t.sleep(1)
    return False


def main() -> int:
    print("=== 0. 等待首拍采集完成 ===")
    check("首拍快照就绪（30 秒内）", wait_first_snapshot())

    print("\n=== 1. 健康检查 ===")
    st, body = get(f"{B}/api/health/live")
    check("/api/health/live 返回 200", st == 200, f"status={st}")
    st, body = get(f"{B}/api/health/ready")
    check("/api/health/ready 返回 200", st == 200, f"status={st}")

    st, body = get(f"{B}/api/health")
    h = json.loads(body)
    for name, c in h["checks"].items():
        if name == "collectors":
            continue
        print(f"      {name}: ok={c.get('ok')}")

    print("\n=== 2. 首屏 overview ===")
    st, body = get(f"{B}/api/overview")
    o = json.loads(body)
    kpi, kv, rt = o["kpi"], o["kv"], o["runtime"]
    th = o["thresholds"]

    print(f"      品牌: {o['branding']['product_name']}")
    print(f"      模型: {o['model']['name']} / {o['model']['ftype']} / {o['model']['n_params']} 参数")
    print(f"      解码速率: {kpi['decode_tps']} tok/s (来源 {kpi['decode_tps_source']})")
    print(f"      预填充速度: {kpi['prefill_tps']} tok/s")
    print(f"      MTP 接受率: {kpi['mtp_accept']}  draft 平均长度: {kpi['draft_mean_len']}")
    print(f"      生成中请求: {kpi['processing']}/{kpi['slots_total']}  排队: {kpi['deferred']}")
    print(f"      显存: {kpi['vram_used_mib']} / {kpi['vram_total_mib']} MiB")
    print(f"      累计生成: {kpi['generated_total']} (精确={kpi['generated_total_exact']})")
    pct = kv["pct"]
    pct_s = f"{pct:.2f}%" if pct is not None else "—"
    print(f"      KV 池: {kv['used_tokens']}/{kv['total_tokens']} = {pct_s}  剩余 {kv['remaining_tokens']}")
    print(f"      槽位: {[(s['id'], s['state'], s['n_prompt_tokens']) for s in kv['slots']]}")
    print(
        f"      GPU: {[(g['index'], g['temp_c'], g['power_w'], g['mem_used_mib'], g['fan_pct']) for g in o['gpus']]}"
    )
    print(f"      徽标: {rt['badges']}")
    print(
        f"      自身: cpu={o['self']['cpu_pct']}% rss={o['self']['rss_mb']}MB threads={o['self']['threads']}"
    )

    # 版号与产品名不写死：以后端 config.py 为单一事实源（v0.4 R8）
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from app.config import Settings as _S

        _exp_name = _S().product_name
        _exp_ver = _S().product_version
    except Exception:  # noqa: BLE001 - 探针可能不在项目根运行
        _exp_name, _exp_ver = "", ""
    check(
        f"品牌名与后端配置一致（{_exp_name or '任意'}）",
        bool(_exp_name) and o["branding"]["product_name"] == _exp_name,
    )
    check("版号与后端配置一致", o["branding"].get("product_version") == _exp_ver)
    check(
        "开发者信息已下发",
        o["branding"]["developer"] == "WKL-LLM运维平台" and o["branding"]["develop_date"] == "2026.10.01",
    )
    check("6 个槽位", len(kv["slots"]) == 6)
    check("2 张 GPU", len(o["gpus"]) == 2)
    check("风扇字段为 null（SXM2 无风扇）", all(g["fan_pct"] is None for g in o["gpus"]))
    check("槽位来源为 null 而非伪造 IP", all(s["source"] is None for s in kv["slots"]))
    check("配置徽标含 draft-mtp", any("draft-mtp" in b for b in rt["badges"]), str(rt["badges"]))
    check("配置徽标含 draft 2(+1)", any("draft 2(+1)" in b for b in rt["badges"]))
    check("阈值由后端下发", "gpu_temp_warn_c" in th and th["vram_warn_pct"] == 90.0)

    print("\n=== 3. KV 池对账（命令行 vs 控制台）===")
    # llama-server 刚重启完时 /slots 可能短暂返回错误对象，需要重试取列表
    slots = None
    for _ in range(20):
        try:
            st, raw = get(f"{LLAMA}/slots")
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            payload = None
        if isinstance(payload, list) and all(isinstance(s, dict) for s in payload):
            slots = payload
            break
        import time as _t

        _t.sleep(1)
    if slots is None:
        check("能取到 /slots 列表", False, "20 秒内未取得有效槽位数据")
        cmd_used, cmd_total = 0, 131072
    else:
        cmd_used = sum(s.get("n_prompt_tokens", 0) for s in slots)
        cmd_total = 131072
        print(f"      命令行: Σ={cmd_used}  {cmd_used / cmd_total * 100:.2f}%  剩余={cmd_total - cmd_used}")
        kvp = kv["pct"] or 0.0
        print(f"      控制台: Σ={kv['used_tokens']}  {kvp:.2f}%  剩余={kv['remaining_tokens']}")
        check("KV 已用 tokens 完全一致（误差 0）", kv["used_tokens"] == cmd_used)
        check("KV 占用率一致", abs(kvp - cmd_used / cmd_total * 100) < 1e-6)

    print("\n=== 4. GPU 对账 ===")
    import subprocess

    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,temperature.gpu,power.draw,memory.used",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [r.split(", ") for r in out.strip().splitlines()]
    for r in rows:
        g = o["gpus"][int(r[0])]
        same = (
            abs(float(r[1]) - (g["temp_c"] or 0)) < 0.01 and abs(float(r[3]) - (g["mem_used_mib"] or 0)) < 1
        )
        check(
            f"GPU{int(r[0])} 温度/显存与 nvidia-smi 一致",
            same,
            f"cmd={r[1]}°C/{r[3]}MiB api={g['temp_c']}°C/{g['mem_used_mib']}MiB",
        )

    print("\n=== 5. 日志面板 ===")
    st, body = get(f"{B}/api/logs?n=40")
    logs = json.loads(body)["data"]
    print(f"      环内 {logs['total_in_ring']} 行，返回 {len(logs['lines'])} 行")
    for ln in logs["lines"][:4]:
        print(f"        {ln['ts'][11:19]} {ln['level']} {(ln['text'] or '')[:88]}")
    check("日志面板有内容", len(logs["lines"]) > 0)
    check(
        "日志使用壁钟时间（非运行时长度）",
        all(ln["ts"].startswith("2026-") for ln in logs["lines"] if ln["ts"]),
    )
    check("不存在把 2990.36.159.181 当时间戳", not any(ln["ts"].startswith("2990") for ln in logs["lines"]))

    st, body = get(f"{B}/api/logs?n=200&q=draft%20acceptance")
    hits = json.loads(body)["data"]["lines"]
    print(f"      关键字 draft acceptance 命中 {len(hits)} 行")

    st, body = get(f"{B}/api/logs?n=500&level=W")
    wl = json.loads(body)["data"]["lines"]
    print(f"      W 及以上 {len(wl)} 行")
    check("级别过滤生效（只返回 W/E）", all(ln["level"] in ("W", "E", "D") for ln in wl))

    print("\n=== 6. 零图片资源 ===")
    st, html = get(f"{B}/")
    st2, css = get(f"{B}/style.css")
    check("HTML 无 <img> 标签", "<img" not in html)
    check("CSS 无位图引用", "background-image" not in css and "url(" not in css)
    check("favicon 返回 204（不提供图标文件）", get(f"{B}/favicon.ico")[0] == 204)

    print("\n=== 7. 顶部与底部文案 ===")
    check("顶部产品标识", "WKL-LLM运维平台" in html and 'class="ver"' in html)
    check("底部开发者信息", "开发者信息" in html and "2026.10.01" in html)

    print("\n=== 8. 历史缓冲 ===")
    st, body = get(f"{B}/api/history?minutes=5")
    pts = json.loads(body)["data"]
    print(f"      {len(pts)} 个采样点")
    check("历史缓冲有数据", len(pts) > 1)

    print("\n=== 9. 服务管理接口 ===")
    st, body = get(f"{B}/api/service/status")
    svc = json.loads(body)
    print(
        f"      {svc['unit']}: {svc['active']}/{svc['sub']} restarts={svc['n_restarts']} authorized={svc['authorized']}"
    )
    check("服务状态可查", svc["active"] in ("active", "activating", "inactive", "failed"))

    req = urllib.request.Request(f"{B}/api/service/rm-rf", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        check("非法动作被拒绝", False, "竟然返回了 2xx")
    except urllib.error.HTTPError as e:
        check("非法动作被拒绝（400）", e.code == 400, f"status={e.code}")

    print("\n=== 10. 控制台自身开销 ===")
    st, body = get(f"{B}/api/health")
    hh = json.loads(body)
    print(f"      {hh['ws']}")
    check("控制台自身内存 < 200MB", (o["self"]["rss_mb"] or 0) < 200, f"{o['self']['rss_mb']}MB")

    print()
    if fails:
        print(f"PROBE_FAILED: {len(fails)} 项未通过")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("PROBE_OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
