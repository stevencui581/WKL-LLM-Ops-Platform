#!/usr/bin/env python
"""打印测试报告所需的摘要（从 build/report_data.json 读取）。

./venv/bin/python probes/print_report_summary.py
"""

from __future__ import annotations

import json
import os
import sys

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "report_data.json")


def main() -> int:
    with open(PATH, encoding="utf-8") as f:
        d = json.load(f)

    print(f"COLLECTED_AT   {d['collected_at']}")
    print(f"PYTEST_TAIL    {d['pytest_tail'][-1].strip() if d['pytest_tail'] else ''}")
    print(f"RUFF           {d['ruff'] or 'All checks passed!'}")
    print(f"FORMAT         {d['ruff_format']}")
    print(f"MYPY           {d['mypy']}")
    print(f"SERVICE        {d['service'].replace(chr(10), ' | ')}")
    print(f"LLAMA_APP      {d['llama_active']}")
    print(f"RELEASE        {d['current_release']}")
    print(f"BRANDING       {d['branding']['product_name']} / {d['branding']['product_version']}")
    print(f"BADGE          {d['accel_badge']['text']} · 张量并行={d['accel_badge']['tensor_parallel']}")
    print(f"KV             {d['kv']['label']}")
    print(f"KV_MODE        {d['kv']['capacity_mode']} (source={d['kv']['capacity_source']})")
    print(
        f"KV_CAPACITY    {d['kv']['total_tokens']} tokens, used={d['kv']['used_tokens']}, "
        f"pct={d['kv']['pct']:.2f}%"
    )
    print(f"KV_QUANT       {d['kv']['kv_quant']} (source={d['kv']['kv_quant_source']})")
    print(f"KV_SLOTS       {d['kv_slots']}")
    print(f"BASELINE       mtp={d['baseline']['mtp']['state']} decode={d['baseline']['decode']['state']}")
    print(f"LLAMA_UPTIME   {d['llama_uptime_s']}")
    print(f"THRESHOLDS     {d['thresholds']}")
    rt = d["runtime"]
    print(
        f"RUNTIME        split={rt['split_mode']} tensor_parallel={rt['tensor_parallel']} "
        f"bw_label={rt['gpu_bandwidth_label']}"
    )
    print(f"BADGES         {rt['badges']}")
    s = d["system"]
    print(
        f"DISK           total={s['disk_total_gb']} GiB used={s['disk_used_gb']} GiB "
        f"pct={s['disk_pct']}%   (期望 283.8 / 166.1 / 58.6)"
    )
    print(f"CPU_MEM        cpu={s['cpu_pct']}% mem={s['mem_used_mb']}/{s['mem_total_mb']} MB")
    print(
        f"SELF           cpu={d['self']['cpu_pct']}% rss={d['self']['rss_mb']}MB "
        f"threads={d['self']['threads']} ws={d['self']['ws_clients']}"
    )
    print(
        f"GPUS           {[(g['index'], g['temp_c'], g['power_w'], g['fan_pct'], g['bandwidth_gbps']) for g in d['gpus']]}"
    )
    print(f"HW_WALL_MS     {d['hw_refresh_wall_ms']}")
    print(f"CMD_ERRORS     {d['command_errors']}")
    hw = d["hardware"]
    print(f"HW_VENDORS     {hw['vendors']}  amd_present={hw['amd_present']}")
    print(f"HW_UNKNOWN     {hw['unknown_fields']} errors={hw['errors']}")
    nb = hw["nvidia"]
    print(
        f"HW_NVIDIA      {nb['model']} ×{nb['count']} bw={nb['bandwidth_gbps']} "
        f"topo={nb['topology']} nvlink={nb['nvlink']}"
    )
    print(f"HW_COMPONENTS  {[(c['name'], c['version'], c['status']) for c in nb['components']]}")
    print(f"HW_PYTHON      {hw['python']['version']} torch={hw['python']['torch']['installed']}")

    if "alert_catalog_count" in d:
        print(
            f"V043_CATALOG   {d['alert_catalog_count']} 个告警代码 · 样例 {d['alert_catalog_sample']['name']}"
        )
        al = d["alert_log"]
        print(
            f"V043_ALERTLOG  total={al['total']} returned={al['returned']} "
            f"limit={al['limit']} by_event={al['by_event']}"
        )
        if al["sample"]:
            s = al["sample"]
            print(
                f"               样例 {s['iso']} | {s['category']['zh']} | {s['name']['zh']} | {s['event']}"
            )
        lh = d["log_history"]
        print(f"V043_HISTORY   档位={lh['days_options']}  实时上限={lh['30']['live_max_lines']}")
        for k in ("1", "7", "30"):
            v = lh[k]
            print(
                f"                 {k:>2}天: 返回 {v['returned']:>6} 行, "
                f"实际覆盖 {v['covered_days']:>5} 天, {v['covered_from']} ~ {v['covered_to']}"
            )
        if "sample_line" in lh:
            print(f"               首行 ts_local = {lh['sample_line']['ts_local']}")
        print(f"V043_BADGES    {[i['key'] for i in (d['badge_items'] or [])]}")
        print(f"V043_REASONS   {d['reason_codes']}")
    print("OBSERVE        " + d["observe"].replace(chr(10), " | ")[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
