#!/usr/bin/env python
"""诊断：取消事件是否被控制台识别（在 目标 上运行）。

cd /home/llmops/llm-console && ./venv/bin/python probes/diag_cancel.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

B = "http://127.0.0.1:8081"


def main() -> int:
    print("=== 1. 控制台当前告警与健康 ===")
    o = json.load(urllib.request.urlopen(f"{B}/api/overview", timeout=30))
    print("  alerts =", json.dumps(o["alerts"], ensure_ascii=False))
    print("  health.ready =", o["health"].get("ready"), " reason_codes =", o["health"].get("reason_codes"))

    print("\n=== 2. 用真实日志行验证 LogStats 解析 ===")
    from app.services.log_stats import LogStats

    samples = [
        "206.40.125.385 W srv          stop: cancel task, id_task = 47734",
        "0.06.106.069 I srv  llama_server: model loaded",
        "105.09.666.215 I slot      release: id 5 | task 41523 | stop processing: n_tokens = 40956, truncated = 0",
    ]
    st = LogStats()
    for s in samples:
        before = st.cancel_events
        st.update(s, 1791000000.0)
        print(f"  cancel {before} -> {st.cancel_events}   | {s[:64]}")
    print(
        f"  exit_events={st.exit_events} truncated={st.truncated_events} "
        f"cancel={st.cancel_events} model_loaded_ts={st.model_loaded_ts}"
    )

    print("\n=== 3. 用 AlertEngine 验证 CLIENT_CANCEL → 告警日志 ===")
    from app.config import Settings
    from app.models import MetricSnapshot
    from app.services.alert_log import AlertLog
    from app.services.alerts import AlertEngine

    tmp = "/tmp/diag-cancel"
    os.makedirs(tmp, exist_ok=True)
    s = Settings(state_dir=tmp, alert_log_path=os.path.join(tmp, "a.jsonl"))
    al = AlertLog(path=s.alert_log_resolved_path)
    eng = AlertEngine(s, None, al)
    eng.note_cancel()
    alerts = eng.evaluate(MetricSnapshot(ts=1791000000.0))
    print("  evaluate 返回的告警 =", [(a.code, a.level, a.message) for a in alerts])
    print("  告警日志条数 =", al.total)
    if al.total:
        e = al.recent(5)[0]
        print("  记录:", json.dumps(e.as_public(), ensure_ascii=False))

    print("\n=== 4. 接口层 ===")
    d = json.load(urllib.request.urlopen(f"{B}/api/alert-log?limit=500", timeout=30))["data"]
    print("  /api/alert-log total =", d["total"], " returned =", d["returned"])

    ok = st.cancel_events == 1 and al.total >= 1
    print("\nDIAG_OK" if ok else "\nDIAG_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
