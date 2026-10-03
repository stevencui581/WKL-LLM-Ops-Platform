#!/usr/bin/env python
"""探测：各推理框架的版本号来源与能力接口（v0.5 第 1 步设计依据）。

./venv/bin/python probes/probe_framework_sources.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"


def get(path: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, f"<{type(exc).__name__}>"


def main() -> int:
    print("=== 1. 各框架的候选探测端点在本机（llama.cpp）上的表现 ===")
    for path in (
        "/props",
        "/slots",
        "/health",
        "/v1/models",
        "/version",
        "/api/version",
        "/api/tags",
        "/api/ps",
        "/get_model_info",
        "/get_server_info",
        "/metrics",
        "/api/generate",
    ):
        code, body = get(path)
        preview = body.replace("\n", " ")[:90]
        print(f"  {code:>4}  {path:<18} {preview}")

    print("\n=== 2. /props 里有没有版本字段？（决定 llama.cpp 版本来源）===")
    code, body = get("/props")
    if code == 200:
        try:
            d = json.loads(body)
            print(f"  顶层键: {sorted(d.keys())}")
            for k in d:
                if any(t in k.lower() for t in ("version", "build", "commit", "model")):
                    print(f"    {k} = {d[k]!r}")
            dg = d.get("default_generation_settings") or {}
            print(f"  default_generation_settings 键: {sorted(dg.keys())[:12]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  解析失败: {exc}")

    print("\n=== 3. journal 里的版本横幅 ===")
    import subprocess

    for pat in ("version", "build:", "llama_server"):
        try:
            out = subprocess.run(
                ["journalctl", "-u", "llm-infer.service", "--no-pager", "-n", "4000", "-o", "cat"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        except Exception as exc:  # noqa: BLE001
            print(f"  journalctl 不可用: {exc}")
            return 0
        hits = [ln for ln in out.splitlines() if pat in ln.lower()][:4]
        print(f"  含 {pat!r}（前 4 条）：")
        for h in hits:
            print(f"    {h.strip()[:110]}")
        break

    print("\n=== 4. unit 的 ExecStart（可取二进制路径跑 --version）===")
    try:
        out = subprocess.run(
            ["systemctl", "show", "llm-infer.service", "-p", "ExecStart", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        print(f"  {out[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  不可用: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
