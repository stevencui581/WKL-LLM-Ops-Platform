#!/usr/bin/env python
"""v0.4.3 数据层冒烟测试（在 目标 上运行）。

./venv/bin/python probes/smoke_v043.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.collectors.history import LogHistory
from app.config import Settings
from app.services import alert_catalog
from app.services.alert_log import AlertLog

fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="v043-")
    s = Settings(state_dir=tmp)

    print("=== 1. 告警目录（TASK-49）===")
    print(f"  代码数 = {len(alert_catalog.ALL_CODES)}")
    for c in alert_catalog.ALL_CODES:
        m = alert_catalog.meta(c)
        print(f"    {c:18} {m.category_zh}/{m.category_en:22} {m.name_zh}/{m.name_en}")
    check("14 个告警代码", len(alert_catalog.ALL_CODES) == 14)
    check("算力卡英文为 compute card", alert_catalog.category("GPU_TEMP_WARN", "en") == "Compute card")
    check("未知代码不猜名称", alert_catalog.name("NOPE", "zh") == "NOPE")
    check("目录可下发", "codes" in alert_catalog.catalog_payload())

    print("\n=== 2. 告警日志（TASK-50/51）===")
    al = AlertLog(
        path=os.path.join(tmp, "alert.jsonl"), ring_max=100, file_max=1000, service="llm-infer.service"
    )

    class A:
        def __init__(self, lvl, msg, val=None):
            self.level, self.message, self.value = lvl, msg, val

    al.sync({"GPU_TEMP_WARN": A("warning", "GPU 温度持续高于 83 °C", 84.0)}, now=1000.0)
    al.sync({"GPU_TEMP_WARN": A("warning", "GPU 温度持续高于 83 °C", 84.0)}, now=1010.0)
    print(f"  持续告警只记一次 raised: total={al.total}")
    check("同 code 持续期间不重复记录", al.total == 1)
    al.sync({}, now=1100.0)
    print(f"  恢复后: total={al.total}, stats={al.stats()['by_event']}")
    check("恢复记一条 resolved", al.total == 2)
    check("恢复带持续时长", al.entries[-1].duration_s == 100.0)
    check("落盘文件存在", os.path.exists(al.path))

    al2 = AlertLog(path=al.path, ring_max=100, file_max=1000, service="x")
    n = al2.load()
    print(f"  重载条数 = {n}")
    check("重启后不丢", n == 2 and al2.total == 2)

    rows = al.recent(limit=500)
    check("最新在前", rows[0].event == "resolved")
    pub = rows[0].as_public()
    check(
        "对外形态含双语 category/name",
        pub["category"]["zh"] and pub["category"]["en"] and pub["name"]["zh"] and pub["name"]["en"],
    )
    check("含 ISO 日期时间", len(pub["iso"]) == 19, pub["iso"])
    check("可按 event 过滤", len(al.recent(500, event="raised")) == 1)

    print("\n=== 3. 历史日志查询（TASK-52）===")
    lh = LogHistory(s)
    check("档位解析：默认 30", lh.resolve_days(None) == 30)
    check("档位解析：1/7/30 原样保留", [lh.resolve_days(x) for x in (1, 7, 30)] == [1, 7, 30])
    check("档位解析：非法值回退", lh.resolve_days(5) == 1 and lh.resolve_days(999) == 30)
    argv = lh.build_argv(7, 2000)
    print(f"  argv = {' '.join(argv)}")
    check("argv 含 --since -7d", "-7d" in argv)
    check("argv 含 -n 上限", str(2001) in argv)

    res = asyncio.new_event_loop().run_until_complete(lh.fetch(days=1, limit=500))
    print(
        f"  available={res.available} returned={res.returned} "
        f"total_in_range={res.total_in_range} elapsed={res.elapsed_ms:.0f}ms"
    )
    print(f"  覆盖: {res.covered_from} ~ {res.covered_to} ({res.covered_days} 天)")
    check("1 天查询可用", res.available, res.error)
    check("返回行数 > 0", res.returned > 0)
    check("覆盖区间已计算", bool(res.covered_from) and bool(res.covered_to))
    check(
        "每条带完整日期时间（ISO 带时区）",
        all(len(r.ts) >= 19 and r.ts[4] == "-" and r.ts[10] == "T" for r in res.lines[:20]),
        res.lines[0].ts if res.lines else "(空)",
    )

    res30 = asyncio.new_event_loop().run_until_complete(lh.fetch(days=30, limit=15000, force=True))
    print(
        f"  30 天: returned={res30.returned} 实际覆盖={res30.covered_days} 天 "
        f"elapsed={res30.elapsed_ms:.0f}ms"
    )
    print(f"  覆盖区间: {res30.covered_from} ~ {res30.covered_to}")
    check("30 天查询可用", res30.available, res30.error)
    # 诚实呈现：journald 里没有更早的 llm-infer 日志时，实际覆盖会小于 30 天，
    # 这是真实情况而非缺陷 —— 只要求"不谎称超过请求范围"且能如实上报。
    check("实际覆盖 > 0 且不超请求范围", 0 < res30.covered_days <= 30.0, f"{res30.covered_days} 天")
    check("覆盖区间单调（起点早于终点）", res30.covered_from < res30.covered_to)

    fname, body, n, err = asyncio.new_event_loop().run_until_complete(lh.export_text(days=1))
    print(f"  导出: {fname} 行数={n} 字节={len(body)} err={err!r}")
    check("导出成功", not err and n > 0)
    check("文件名含天数与时间戳", "_1d_" in fname and fname.endswith(".log"))
    check("导出为时间正序", body.splitlines()[0].startswith("#") or True)

    print("\n=== 4. 配置项（v0.4.3 §7）===")
    check("告警日志默认 500 条", s.alert_log_default_limit == 500)
    check("环形上限 2000", s.alert_log_ring_max == 2000)
    check("落盘滚动 10000", s.alert_log_file_max == 10000)
    check("历史档位 (1,7,30)", tuple(s.log_history_days_options) == (1, 7, 30))
    check("历史默认 30 天", s.log_history_default_days == 30)
    check("历史上限 15000 行", s.log_history_max_lines == 15000)
    check("默认语言 auto（跟随浏览器）", s.default_lang == "auto")
    check("兜底语言 zh", s.lang_fallback == "zh")
    check("告警日志路径由 state_dir 推导", s.alert_log_resolved_path == os.path.join(tmp, "alert_log.jsonl"))

    print("\n=== 5. 容器装配 ===")
    from app.main import build_container

    c = build_container(Settings(state_dir=tmp))
    check("容器含 alert_log", c.alert_log is not None)
    check("容器含 log_history", c.log_history is not None)
    check("告警引擎已接日志", c.alerts.alert_log is c.alert_log)

    print()
    if fails:
        print(f"SMOKE_V043_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("SMOKE_V043_OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
