#!/usr/bin/env bash
# 全量验收套件（方案第十一章）
#   bash deploy/verify_all.sh
set -uo pipefail
cd "$(dirname "$0")/.."
VENV=./venv/bin
# 被监控的推理单元名**从运行中的服务读**（API 是唯一事实源）。
#
# 不要用 `python -c 'Settings().llama_unit'` —— 那会拿到 config.py 的通用默认值，
# 而真实单元名是部署时由 systemd 单元文件通过 LLMCONSOLE_LLAMA_UNIT 注入的，
# 新起的 Python 进程看不到。实测踩过：这里会误报 inactive。
INFER_UNIT="$(curl -s --max-time 5 http://127.0.0.1:8081/api/service/status \
  | "$VENV/python" -c 'import json,sys; print(json.load(sys.stdin).get("unit",""))' 2>/dev/null \
  || true)"
[ -n "$INFER_UNIT" ] || INFER_UNIT=unknown

rc=0
run() {
  local title="$1"; shift
  echo
  echo "################ $title ################"
  if "$@"; then
    echo ">>> $title: OK"
  else
    echo ">>> $title: FAILED"
    rc=1
  fi
}

run "1/10 质量门禁（ruff + format + mypy + pytest）" bash selfcheck.sh
run "2/10 前端静态自检（三个页面 + 双语）" "$VENV/python" deploy/check_frontend.py
run "3/10 端到端功能验收" "$VENV/python" deploy/probe_e2e.py
run "4/10 WebSocket 通道验收" "$VENV/python" deploy/probe_ws.py
run "5/10 服务管理验收（只读，不触发重启）" "$VENV/python" deploy/probe_service.py
# v0.4.3 新增：真实链路验证（会真实触发一次推理，不影响生产）
run "6/10 线上能力验收（v0.4 ~ v0.6）" "$VENV/python" probes/check_v04_live.py
run "7/10 告警日志全链路（产生→恢复→落盘）" "$VENV/python" probes/e2e_alert_log.py
run "8/10 实时日志通道（backfill→增量→释放）" "$VENV/python" probes/e2e_live_log.py
# v0.4.4 新增：历史缺陷的修复台账（源码扫描 + 行为判据，D1~D9）
run "9/10 缺陷修复台账（D1~D9）" "$VENV/python" probes/audit_defects.py
# v0.5 新增：WebSocket 快照字段完整性。
# 必须直连 WebSocket —— REST 探针查不出「字段只挂在 REST 上」这类缺陷，
# 而那正是「框架徽标一直显示识别中」的根因。
run "10/10 WebSocket 快照字段完整性" "$VENV/python" probes/e2e_ws_snapshot.py

echo
echo "################ 运行状态 ################"
systemctl show llm-console.service -p ActiveState,SubState,NRestarts,MemoryCurrent,WatchdogUSec --no-pager
echo "当前版本: $(readlink -f current)"
echo "被监控单元: $INFER_UNIT = $(systemctl is-active "$INFER_UNIT" 2>/dev/null || echo unknown)"
curl -s -o /dev/null -w '/metrics = %{http_code}\n' http://127.0.0.1:8080/metrics

echo
if [ "$rc" -eq 0 ]; then echo "VERIFY_ALL_OK"; else echo "VERIFY_ALL_FAILED"; fi
exit "$rc"
