"""稳定性观察采样（方案 TASK-24 / 验收标准 11.3）。

每 12 小时采一次样，追加到 state/observation.jsonl；
随时可打印汇总报告。

    ./venv/bin/python deploy/observe.py --sample     # 采一次样
    ./venv/bin/python deploy/observe.py --report     # 打印汇总
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

ROOT = "/home/llmops/llm-console"
STATE = os.path.join(ROOT, "state")
OBS = os.path.join(STATE, "observation.jsonl")
UNIT = "llm-console.service"
API = "http://127.0.0.1:8081"


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def systemd_props() -> dict:
    out = sh(
        [
            "systemctl",
            "show",
            UNIT,
            "-p",
            "ActiveState,SubState,NRestarts,MemoryCurrent,CPUUsageNSec,WatchdogUSec",
        ]
    )
    d = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip()
    return d


def api(path: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
            return json.load(r)
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def sample() -> dict:
    os.makedirs(STATE, exist_ok=True)
    props = systemd_props()
    health = api("/api/health")
    overview = api("/api/overview")
    rec = {
        "ts": time.time(),
        "iso": datetime.now().astimezone().isoformat(timespec="seconds"),
        "active": props.get("ActiveState"),
        "sub": props.get("SubState"),
        "n_restarts": props.get("NRestarts"),
        "mem_mb": round(int(props.get("MemoryCurrent") or 0) / 1048576, 1),
        "cpu_s": round(int(props.get("CPUUsageNSec") or 0) / 1e9, 1),
        "watchdog_usec": props.get("WatchdogUSec"),
        "ready": health.get("ok") if isinstance(health, dict) else None,
        "reasons": health.get("reasons") if isinstance(health, dict) else None,
        "counters": health.get("counters") if isinstance(health, dict) else None,
        "ws": health.get("ws") if isinstance(health, dict) else None,
        "self_rss_mb": (overview.get("self") or {}).get("rss_mb") if isinstance(overview, dict) else None,
        "self_cpu_pct": (overview.get("self") or {}).get("cpu_pct") if isinstance(overview, dict) else None,
        "kv_pct": (overview.get("kv") or {}).get("pct") if isinstance(overview, dict) else None,
        "alerts": [a.get("code") for a in (overview.get("alerts") or [])]
        if isinstance(overview, dict)
        else None,
    }
    with open(OBS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def load() -> list[dict]:
    if not os.path.exists(OBS):
        return []
    out = []
    with open(OBS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def report() -> int:
    recs = load()
    if not recs:
        print("还没有采样记录。先运行 deploy/observe.py --sample")
        return 1
    first, last = recs[0], recs[-1]
    span_h = (last["ts"] - first["ts"]) / 3600.0
    print("=== 稳定性观察报告（方案 TASK-24 / 11.3）===")
    print(f"样本数        : {len(recs)}")
    print(f"观察时长      : {span_h:.1f} 小时（目标 72 小时）")
    print(f"起始 / 结束   : {first['iso']}  →  {last['iso']}")

    downs = [r for r in recs if r.get("active") != "active"]
    restarts = max((int(r.get("n_restarts") or 0) for r in recs), default=0)
    mems = [r["mem_mb"] for r in recs if r.get("mem_mb") is not None]
    rsss = [r["self_rss_mb"] for r in recs if r.get("self_rss_mb") is not None]
    cpus = [r["self_cpu_pct"] for r in recs if r.get("self_cpu_pct") is not None]
    notready = [r for r in recs if r.get("ready") is False]

    print(f"非 active 次数: {len(downs)}")
    print(f"重启次数      : {restarts}")
    print(f"服务内存      : min={min(mems) if mems else '—'} MB  max={max(mems) if mems else '—'} MB")
    print(f"控制台 RSS    : min={min(rsss) if rsss else '—'} MB  max={max(rsss) if rsss else '—'} MB")
    print(f"控制台 CPU    : max={max(cpus) if cpus else '—'} %")
    print(f"readiness 失败: {len(notready)} 次")
    if rsss and len(rsss) > 1:
        drift = rsss[-1] - rsss[0]
        print(f"RSS 漂移      : {drift:+.1f} MB（>50MB 需排查内存增长）")

    ok = (
        span_h >= 72
        and not downs
        and restarts == 0
        and len(notready) == 0
        and (max(rsss) if rsss else 0) < 200
    )
    print()
    print("OBSERVE_OK: 72 小时观察通过" if ok else "OBSERVE_PENDING: 观察未达标或尚未满 72 小时")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        sys.exit(report())
    sample()
