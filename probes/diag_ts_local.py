#!/usr/bin/env python
"""诊断历史日志的 ts_local 形态（v0.6）。

cd "$WKL_ROOT" && ./venv/bin/python probes/diag_ts_local.py
"""

from __future__ import annotations

import collections
import json
import sys
import urllib.request

B = "http://127.0.0.1:8081"


def main() -> int:
    for limit in (None, 200, 2000, 15000):
        q = "?days=1" if limit is None else f"?days=1&limit={limit}"
        try:
            with urllib.request.urlopen(f"{B}/api/logs/history{q}", timeout=90) as r:
                raw = json.load(r)
        except Exception as exc:  # noqa: BLE001
            print(f"limit={limit}: 请求失败 {type(exc).__name__}: {exc}")
            continue
        # 路由返回信封结构 {ts, seq, stale, data:{...}}
        h = raw.get("data", raw)
        lines = h.get("lines") or []
        print(f"=== limit={limit} ===")
        print(
            f"  available={h.get('available')} returned={h.get('returned')} "
            f"error={h.get('error')!r} cached={h.get('cached')}"
        )
        print(f"  covered={h.get('covered_days')} {h.get('covered_from')} ~ {h.get('covered_to')}")
        if not lines:
            continue
        lens = collections.Counter(len(x.get("ts_local", "")) for x in lines)
        print(f"  ts_local 长度分布: {dict(lens)}")
        shown = 0
        for i, x in enumerate(lines):
            tl = x.get("ts_local", "")
            if len(tl) != 19:
                print(f"  [非 19] 第 {i} 行 len={len(tl)} ts_local={tl!r}")
                print(f"          text={x.get('text', '')[:160]!r}")
                shown += 1
                if shown >= 3:
                    break
    return 0


if __name__ == "__main__":
    sys.exit(main())
