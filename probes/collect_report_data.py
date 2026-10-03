"""测试报告数据采集（在 目标 上运行，输出 JSON 供报告使用）。

./venv/bin/python probes/collect_report_data.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

ROOT = "/home/llmops/llm-console"
B = "http://127.0.0.1:8081"


def sh(cmd: list[str], timeout: int = 120) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"<error {exc}>"


def get(path: str):
    with urllib.request.urlopen(f"{B}{path}", timeout=15) as r:
        return json.load(r)


def main() -> int:
    out: dict = {}
    out["collected_at"] = time.strftime("%Y-%m-%d %H:%M:%S%z")

    # ---- 测试总数 ----
    txt = sh([f"{ROOT}/venv/bin/python", "-m", "pytest", "--no-header", "-q"])
    out["pytest_tail"] = [ln for ln in txt.strip().splitlines() if ln.strip()][-3:]
    out["ruff"] = sh([f"{ROOT}/venv/bin/ruff", "check", "--output-format=concise", "app", "tests"]).strip()[
        -200:
    ]
    out["ruff_format"] = sh([f"{ROOT}/venv/bin/ruff", "format", "--check", "app", "tests"]).strip()[-120:]
    out["mypy"] = sh([f"{ROOT}/venv/bin/mypy", "app"]).strip()[-200:]

    # ---- 服务 ----
    out["service"] = sh(
        [
            "systemctl",
            "show",
            "llm-console.service",
            "-p",
            "ActiveState,SubState,NRestarts,MemoryCurrent,WatchdogUSec",
            "--no-pager",
        ]
    ).strip()
    out["llama_active"] = sh(["systemctl", "is-active", "llm-infer.service"]).strip()
    out["current_release"] = sh(["readlink", "-f", f"{ROOT}/current"]).strip()

    # ---- 接口 ----
    ov = get("/api/overview")
    hw = get("/api/hardware")
    out["branding"] = ov["branding"]
    out["kv"] = {
        k: ov["kv"][k]
        for k in (
            "used_tokens",
            "total_tokens",
            "pct",
            "remaining_tokens",
            "capacity_mode",
            "capacity_source",
            "label",
            "kv_quant",
            "kv_quant_source",
        )
    }
    out["kv_slots"] = len(ov["kv"]["slots"])
    out["accel_badge"] = ov["accelerator_badge"]
    out["baseline"] = ov["baseline"]
    out["llama_uptime_s"] = ov["llama_uptime_s"]
    out["thresholds"] = ov["thresholds"]
    out["runtime"] = {
        k: ov["runtime"][k]
        for k in (
            "model_name",
            "kv_quant",
            "kv_quant_source",
            "spec_types",
            "draft_n_max",
            "flash_attn",
            "tensor_split",
            "split_mode",
            "tensor_parallel",
            "gpu_count",
            "gpu_bandwidth_label",
            "badges",
        )
    }
    out["system"] = ov["system"]
    out["self"] = ov["self"]
    out["gpu_count"] = len(ov["gpus"])
    out["gpus"] = [
        {
            k: g[k]
            for k in (
                "index",
                "name",
                "temp_c",
                "power_w",
                "power_limit_w",
                "mem_used_mib",
                "mem_total_mib",
                "fan_pct",
                "bandwidth_gbps",
                "mem_type",
                "vendor",
            )
        }
        for g in ov["gpus"]
    ]
    out["hardware"] = {
        "vendors": hw["vendors"],
        "dmi": hw["dmi"],
        "cpu": hw["cpu"],
        "memory": hw["memory"],
        "disks": hw["disks"],
        "nvidia": hw["accelerators"]["nvidia"],
        "amd_present": hw["accelerators"]["amd"]["present"],
        "python": hw["python"],
        "unknown_fields": hw["unknown_fields"],
        "errors": hw["errors"],
    }

    # ---- 硬件清点耗时 ----
    t0 = time.monotonic()
    req = urllib.request.Request(f"{B}/api/hardware?refresh=1")
    with urllib.request.urlopen(req, timeout=60) as r:
        json.load(r)
    out["hw_refresh_wall_ms"] = round((time.monotonic() - t0) * 1000)

    # ---- 命令错误计数（验证可选探测不再计入） ----
    out["command_errors"] = get("/api/health")["counters"].get("command_errors")

    # ---- v0.4.3 新增 ----
    cat = get("/api/alert-catalog")["data"]
    out["alert_catalog_count"] = len(cat["codes"])
    out["alert_catalog_sample"] = cat["codes"]["GPU_TEMP_WARN"]

    alog = get("/api/alert-log?limit=500")["data"]
    out["alert_log"] = {
        "total": alog["total"],
        "returned": alog["returned"],
        "limit": alog["limit"],
        "by_event": alog["stats"]["by_event"],
        "sample": (alog["entries"][0] if alog["entries"] else None),
    }

    hist: dict = {}
    h30 = get("/api/logs/history?days=30")["data"]
    for d in (1, 7, 30):
        h = get(f"/api/logs/history?days={d}")["data"]
        hist[str(d)] = {
            k: h[k]
            for k in (
                "requested_days",
                "returned",
                "total_in_range",
                "covered_days",
                "covered_from",
                "covered_to",
                "truncated",
                "available",
                "elapsed_ms",
                "live_enabled",
                "live_max_lines",
            )
        }
        if d == 30 and h["lines"]:
            hist["sample_line"] = {k: h["lines"][0].get(k) for k in ("ts", "ts_local", "level", "text")}
    hist["days_options"] = h30["days_options"]
    out["log_history"] = hist
    out["badge_items"] = ov["runtime"].get("badge_items")
    out["reason_codes"] = ov["health"].get("reason_codes")
    out["pages"] = ["/", "/alerts.html", "/logs.html"]

    # ---- 稳定性观察 ----
    out["observe"] = sh([f"{ROOT}/venv/bin/python", "deploy/observe.py", "--report"]).strip()

    txt = json.dumps(out, ensure_ascii=False, indent=2)
    with open(f"{ROOT}/build/report_data.json", "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
