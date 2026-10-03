"""推理吞吐基线/对比测量（TASK-02 验收：重启前后吞吐差异 < 5%）。

向 llama-server 发一个**固定**请求，读取返回的 timings。
    ./venv/bin/python deploy/bench_infer.py --label before
    ./venv/bin/python deploy/bench_infer.py --label after --compare
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

LLAMA = "http://127.0.0.1:8080"
STATE = "/home/llmops/llm-console/state"
BENCH = os.path.join(STATE, "bench.jsonl")

PROMPT = "用不超过三句话解释什么是张量并行（tensor parallelism），以及它为什么能加速大模型推理。"
N_PREDICT = 96
ROUNDS = 3


def complete(timeout: float = 180.0) -> dict:
    body = json.dumps(
        {
            "prompt": PROMPT,
            "n_predict": N_PREDICT,
            "temperature": 0.0,
            "top_k": 1,
            "cache_prompt": False,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{LLAMA}/completion", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    wall = time.time() - t0
    t = payload.get("timings") or {}
    return {
        "wall_s": round(wall, 3),
        "prompt_n": t.get("prompt_n"),
        "prompt_tps": t.get("prompt_per_second"),
        "predicted_n": t.get("predicted_n"),
        "decode_tps": t.get("predicted_per_second"),
        "draft_n": t.get("draft_n"),
        "draft_n_accepted": t.get("draft_n_accepted"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="manual")
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()

    os.makedirs(STATE, exist_ok=True)
    runs = []
    for i in range(ROUNDS):
        try:
            r = complete()
        except Exception as exc:  # noqa: BLE001
            print(f"  第 {i + 1} 轮失败: {type(exc).__name__}: {exc}")
            continue
        runs.append(r)
        print(
            f"  第 {i + 1} 轮: prompt {r['prompt_n']} tok @ {r['prompt_tps']:.1f} t/s | "
            f"decode {r['predicted_n']} tok @ {r['decode_tps']:.2f} t/s | "
            f"draft {r['draft_n_accepted']}/{r['draft_n']} | wall {r['wall_s']}s"
        )

    if not runs:
        print("BENCH_FAILED: 没有任何成功的推理请求")
        return 1

    dec = [r["decode_tps"] for r in runs if r["decode_tps"]]
    pre = [r["prompt_tps"] for r in runs if r["prompt_tps"]]
    summary = {
        "label": a.label,
        "ts": time.time(),
        "rounds": len(runs),
        "decode_tps_median": round(statistics.median(dec), 2) if dec else None,
        "decode_tps_min": round(min(dec), 2) if dec else None,
        "prefill_tps_median": round(statistics.median(pre), 2) if pre else None,
        "runs": runs,
    }
    with open(BENCH, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(
        f"\n[{a.label}] decode 中位数 {summary['decode_tps_median']} t/s | "
        f"prefill 中位数 {summary['prefill_tps_median']} t/s"
    )

    if a.compare:
        recs = []
        with open(BENCH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
        before = [r for r in recs if r["label"] == "before"]
        after = [r for r in recs if r["label"] == "after"]
        if not before or not after:
            print("BENCH_PENDING: 缺少 before/after 之一")
            return 1
        b = before[-1]["decode_tps_median"]
        af = after[-1]["decode_tps_median"]
        delta = abs(af - b) / b * 100 if b else 0
        print(f"对比: before {b} → after {af} t/s，差异 {delta:.2f}%")
        ok = delta < 5.0
        print(
            "BENCH_OK: 吞吐差异 < 5%，--metrics 未带来性能损失"
            if ok
            else "BENCH_FAILED: 吞吐差异 >= 5%，需要回滚"
        )
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
