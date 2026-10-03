#!/usr/bin/env python
"""告警日志 + 历史日志的**真实端到端**验证（在 目标 上运行）。

    cd /home/llmops/llm-console && ./venv/bin/python probes/e2e_alert_log.py

做法（不破坏生产）：
  1. 对 llama-server 发一个流式请求，读到几个 token 后**主动断开**；
  2. llama-server 会记录客户端取消 → 控制台的日志跟随器识别为
     ``CLIENT_CANCEL`` 事件 → 告警引擎产生告警 → **写入告警日志**；
  3. 随后调 ``/api/alert-log`` 断言确实出现了这条记录（含时间/类型/名称）。

这是唯一能在不打乱生产阈值的前提下，走通
"日志 → 告警 → 告警日志 → REST 接口" 全链路的办法。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

B = "http://127.0.0.1:8081"
LLAMA = "http://127.0.0.1:8080"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def get(path: str):
    with urllib.request.urlopen(f"{B}{path}", timeout=60) as r:
        return json.load(r)


def cancel_one_generation() -> bool:
    """发一个流式请求后主动断开，触发 llama-server 的客户端取消日志。"""
    payload = json.dumps(
        {
            "prompt": "请用中文写一段 800 字的说明，主题是服务器运维。",
            "n_predict": 400,
            "stream": True,
            "cache_prompt": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{LLAMA}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            # 只读几块就断开，模拟用户关掉页面
            r.read(200)
            time.sleep(0.6)
            r.read(200)
            r.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    (取消请求时出现异常，忽略：{type(exc).__name__})")
        return True


def last_event_of(code: str, entries: list[dict]) -> str:
    for e in entries:  # entries 最新在前
        if e["code"] == code:
            return e["event"]
    return ""


def wait_until_resolved(code: str, timeout: int = 100) -> bool:
    """等待某代码的告警恢复（事件型告警保留 event_alert_ttl_s 秒后自动恢复）。

    必须先等到"已恢复"，否则新触发的取消只会刷新窗口，
    而不会产生新的 raised 记录（差量语义）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = get("/api/alert-log?limit=500")["data"]
        if last_event_of(code, d["entries"]) in ("", "resolved"):
            return True
        time.sleep(3)
    return False


def main() -> int:
    print("=== 1. 等待 CLIENT_CANCEL 处于已恢复状态 ===")
    before = get("/api/alert-log?limit=500")["data"]
    print(f"  记录前 total = {before['total']}, by_event = {before['stats']['by_event']}")
    print(f"  CLIENT_CANCEL 最近事件 = {last_event_of('CLIENT_CANCEL', before['entries']) or '(无)'}")
    got = wait_until_resolved("CLIENT_CANCEL", timeout=100)
    check("CLIENT_CANCEL 已恢复（可用于触发新的 raised）", got)
    before = get("/api/alert-log?limit=500")["data"]

    print("\n=== 2. 触发一次客户端取消（产生真实告警）===")
    ok = cancel_one_generation()
    check("请求已发出并断开", ok)

    print("\n=== 3. 等待控制台识别（采集 2s + 日志跟随）===")
    found = None
    for i in range(15):
        time.sleep(2)
        after = get("/api/alert-log?limit=500")["data"]
        if after["total"] > before["total"]:
            found = after
            print(f"  第 {(i + 1) * 2}s 检测到新记录（total {before['total']} → {after['total']}）")
            break
        print(f"  第 {(i + 1) * 2}s 仍无新记录…")

    check("告警日志产生了新记录", found is not None)
    if found is None:
        print("\nE2E_ALERT_FAILED（未产生记录，可能是日志事件未触发）")
        return 1

    entries = found["entries"]
    newest = entries[0]
    print(f"\n  最新记录： {json.dumps(newest, ensure_ascii=False)}")
    check("记录含 ISO 日期时间", len(newest.get("iso", "")) == 19, newest.get("iso", ""))
    check(
        "记录含服务类型（双语）",
        bool(newest["category"]["zh"]) and bool(newest["category"]["en"]),
        f"{newest['category']['zh']} / {newest['category']['en']}",
    )
    check(
        "记录含服务名称（双语）",
        bool(newest["name"]["zh"]) and bool(newest["name"]["en"]),
        f"{newest['name']['zh']} / {newest['name']['en']}",
    )
    check("新记录为 raised 事件", newest["event"] == "raised", newest["event"])
    check("记录含被监控服务", bool(newest.get("service")), newest.get("service", ""))
    check("记录为客户端取消事件", newest["code"] == "CLIENT_CANCEL", newest["code"])

    print("\n=== 4. 等待自动恢复（事件型告警 TTL）===")
    resolved = wait_until_resolved("CLIENT_CANCEL", timeout=100)
    final = get("/api/alert-log?limit=500")["data"]
    print(f"  最终 total = {final['total']}, by_event = {final['stats']['by_event']}")
    check("事件型告警自动恢复（产生 resolved 记录）", resolved)
    check(
        "统计区分 raised 与 resolved",
        set(final["stats"]["by_event"]) >= {"raised", "resolved"},
        str(final["stats"]["by_event"]),
    )

    print("\n=== 5. 过滤与分页 ===")
    r1 = get("/api/alert-log?limit=500&event=raised")["data"]
    r2 = get("/api/alert-log?limit=500&event=resolved")["data"]
    print(f"  raised 过滤 = {r1['returned']} 条, resolved 过滤 = {r2['returned']} 条")
    check(
        "按 event 过滤生效",
        all(e["event"] == "raised" for e in r1["entries"])
        and all(e["event"] == "resolved" for e in r2["entries"]),
    )
    check(
        "raised + resolved = total",
        r1["returned"] + r2["returned"] == final["total"],
        f"{r1['returned']} + {r2['returned']} vs {final['total']}",
    )

    print("\n=== 6. 落盘文件 ===")
    import os

    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "alert_log.jsonl")
    exists = os.path.exists(p)
    lines = sum(1 for _ in open(p, encoding="utf-8")) if exists else 0
    print(f"  {p}: exists={exists} lines={lines}")
    check("告警日志已落盘", exists and lines > 0)

    print()
    if fails:
        print(f"E2E_ALERT_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("E2E_ALERT_OK: 告警日志全链路通过（产生 → 恢复 → 落盘 → 过滤）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
