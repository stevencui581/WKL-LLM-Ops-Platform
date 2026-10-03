"""WebSocket 通道验收（方案 TASK-12 验收标准）。

在 目标 上执行：
    /home/llmops/llm-console/venv/bin/python deploy/probe_ws.py

验证：
  * /ws/metrics 连接后 2.5 秒内收到 snapshot，字段完整；
  * 连续两帧 seq 单调递增；
  * /ws/logs 连接后立即收到 backfill，且能持续收到 log/ping；
  * 断开后服务端连接计数回落（finally 退订生效）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

import websockets

BASE = "ws://127.0.0.1:8081"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def ws_stats() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8081/api/health", timeout=5) as r:
        return json.load(r)["ws"]


def ws_clients() -> int:
    s = ws_stats()
    return s["metrics_clients"] + s["log_clients"]


async def test_metrics() -> None:
    print("=== /ws/metrics ===")
    async with websockets.connect(f"{BASE}/ws/metrics") as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=2.5)
        msg = json.loads(raw)
        check("2.5 秒内收到首帧", msg.get("type") == "snapshot", str(msg.get("type")))
        p = msg["payload"]
        for key in ("seq", "ts", "stale", "kpi", "kv", "gpus", "runtime", "system", "self"):
            check(f"快照含字段 {key}", key in p)

        # 收集两帧验证 seq 单调
        seqs = [msg["seq"]]
        while len(seqs) < 2:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
            if m.get("type") == "snapshot":
                seqs.append(m["seq"])
            elif m.get("type") == "ping":
                await ws.send("ping")
        check("snapshot seq 单调递增", seqs[1] > seqs[0], f"{seqs}")

        kpi = p["kpi"]
        print(
            f"      decode={kpi['decode_tps']} mtp={kpi['mtp_accept']} "
            f"vram={kpi['vram_used_mib']}/{kpi['vram_total_mib']}"
        )
        print(f"      kv={p['kv']['pct']:.2f}% slots={len(p['kv']['slots'])} gpus={len(p['gpus'])}")


async def test_logs() -> None:
    print("\n=== /ws/logs ===")
    async with websockets.connect(f"{BASE}/ws/logs") as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        check("首帧为 backfill", msg.get("type") == "backfill", str(msg.get("type")))
        lines = msg.get("payload", [])
        check("backfill 有内容", len(lines) > 0, f"{len(lines)} 行")
        if lines:
            ln = lines[0]
            for key in ("ts", "level", "text", "slot", "task", "highlight"):
                check(f"日志行含字段 {key}", key in ln)
            print(f"      示例: {ln['ts'][:19]} {ln['level']} {(ln['text'] or '')[:70]}")
        check(
            "backfill 使用壁钟时间",
            all((line.get("ts") or "").startswith("2026-") for line in lines if line.get("ts")),
        )


async def test_disconnect_cleanup() -> None:
    print("\n=== 断开后连接数回落（finally 退订）===")
    for _ in range(10):  # 先等其他连接彻底释放
        if ws_clients() == 0:
            break
        await asyncio.sleep(0.5)
    before = ws_clients()
    ws = await websockets.connect(f"{BASE}/ws/logs")
    await asyncio.sleep(1.0)
    during = ws_clients()
    await ws.close()
    # 必须有专职读取任务：断线要立刻被发现，不能等到下次发送失败
    after = None
    for _ in range(12):
        await asyncio.sleep(0.25)
        after = ws_clients()
        if after <= before:
            break
    print(f"      before={ws_stats()} during={during} after={ws_stats()}")
    check("连接期间计数 +1", during >= before + 1)
    check("断开后 3 秒内计数回落（无订阅泄漏）", after <= before, f"after={after}")


async def main() -> int:
    await test_metrics()
    await test_logs()
    await test_disconnect_cleanup()
    print()
    if fails:
        print(f"WS_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("WS_OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
