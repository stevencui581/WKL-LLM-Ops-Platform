#!/usr/bin/env bash
# v0.4.3 交付前最终状态确认
set -uo pipefail
B=http://127.0.0.1:8081
cd /home/llmops/llm-console

echo "=== 服务状态 ==="
echo "  llm-console: $(systemctl is-active llm-console.service)"
echo "  llm-infer  : $(systemctl is-active llm-infer.service)"
systemctl show llm-console.service -p NRestarts,MemoryCurrent,WatchdogUSec --no-pager | sed 's/^/  /'
echo "  当前版本   : $(readlink -f current)"

echo
echo "=== 三个页面 ==="
for p in / /alerts.html /logs.html /i18n.js /alerts.js /logs.js; do
  printf '  %s  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B$p")" "$p"
done

echo
echo "=== 版本号（单一来源）==="
curl -s "$B/api/overview" | ./venv/bin/python -c \
  'import json,sys; d=json.load(sys.stdin); print("  ", d["branding"]["product_name"], "/", d["branding"]["product_version"])'

echo
echo "=== 术语抽样（算力卡 / compute card）==="
grep -oE "'top\.accel': '[^']*'" static/i18n.js | sed 's/^/  /'

echo
echo "=== 关键能力自检 ==="
printf '  告警代码数      : %s\n' "$(curl -s "$B/api/alert-catalog" | ./venv/bin/python -c 'import json,sys; print(len(json.load(sys.stdin)["data"]["codes"]))')"
printf '  告警日志条数    : %s\n' "$(curl -s "$B/api/alert-log?limit=500" | ./venv/bin/python -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(d["total"], d["stats"]["by_event"])')"
printf '  历史档位        : %s\n' "$(curl -s "$B/api/logs/history?days=30" | ./venv/bin/python -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(d["days_options"], "30天覆盖", d["covered_days"], "天")')"
printf '  自动基线        : %s\n' "$(curl -s "$B/api/overview" | ./venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print("mtp", d["baseline"]["mtp"]["state"], d["baseline"]["mtp"]["value"], "| decode", d["baseline"]["decode"]["state"], d["baseline"]["decode"]["value"])')"
