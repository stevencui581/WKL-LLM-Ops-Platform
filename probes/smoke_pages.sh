#!/usr/bin/env bash
# v0.4.3 新接口与页面冒烟（在 目标 上运行）
set -uo pipefail
B=http://127.0.0.1:8081
cd /home/llmops/llm-console

echo "=== 1. 新接口 ==="
for p in "/api/alert-catalog" "/api/alert-log?limit=500" "/api/alert-log?limit=500&event=raised" \
         "/api/logs/history?days=30&limit=2000" "/api/logs/history?days=7&limit=100" \
         "/api/logs/history?days=1&limit=100" "/api/logs/history?days=5&limit=100"; do
  code=$(curl -s -o /tmp/o.json -w '%{http_code}' "$B$p")
  size=$(wc -c < /tmp/o.json)
  printf '  %s  %8s B  %s\n' "$code" "$size" "$p"
done

echo
echo "=== 2. 告警目录内容 ==="
curl -s "$B/api/alert-catalog" | ./venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)['data']
c=d['codes']
print('  代码数 =', len(c))
print('  GPU_TEMP_WARN =', c['GPU_TEMP_WARN'])
print('  top.accel(en) =', c['GPU_TEMP_WARN']['category']['en'])
"

echo
echo "=== 3. 历史日志档位与覆盖（用服务端默认 limit）==="
for d in 1 7 30; do
  curl -s "$B/api/logs/history?days=$d" | ./venv/bin/python -c "
import json,sys
x=json.load(sys.stdin)['data']
print('  days=%-2s requested=%-2s returned=%-6s total=%-6s covered=%5.2f 天  %s ~ %s  avail=%s trunc=%s' % (
  '$d', x['requested_days'], x['returned'], x['total_in_range'],
  x['covered_days'], x['covered_from'], x['covered_to'], x['available'], x['truncated']))
"
done

echo
echo "=== 3b. 客户端默认 limit 的覆盖（前端不传 limit 时）==="
curl -s "$B/api/logs/history?days=30" | ./venv/bin/python -c "
import json,sys
x=json.load(sys.stdin)['data']
print('  30 天实际返回 =', x['returned'], '行, 覆盖 =', x['covered_days'], '天')
print('  elapsed_ms =', x['elapsed_ms'])
"

echo
echo "=== 4. 非法档位回退 ==="
curl -s "$B/api/logs/history?days=5&limit=50" | ./venv/bin/python -c "
import json,sys; x=json.load(sys.stdin)['data']
print('  days=5 -> requested =', x['requested_days'], '(应为 1)')
print('  days_options =', x['days_options'])
"

echo
echo "=== 5. 下载 .log ==="
curl -s -D /tmp/h.txt -o /tmp/e.log "$B/api/logs/history/download?days=1"
grep -iE 'HTTP/|content-disposition|content-type|x-export-lines' /tmp/h.txt | sed 's/^/  /'
printf '  实际行数=%s  字节=%s\n' "$(wc -l < /tmp/e.log)" "$(wc -c < /tmp/e.log)"
head -3 /tmp/e.log | sed 's/^/  /'

echo
echo "=== 6. output:overview 新增结构化字段 ==="
curl -s "$B/api/overview" | ./venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
rt=d['runtime']
print('  badge_items =', rt.get('badge_items'))
print('  health.reason_codes =', d['health'].get('reason_codes'))
print('  kv.capacity_mode =', d['kv']['capacity_mode'], ' total =', d['kv']['total_tokens'])
print('  kv.label(兼容) =', d['kv']['label'])
print('  accel.nvidia.bandwidth_known =', d.get('hardware_ts') and '(见 /api/hardware)')
"
curl -s "$B/api/hardware" | ./venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
nb=d['accelerators']['nvidia']
print('  hardware bandwidth_known =', nb.get('bandwidth_known'), ' notes =', nb.get('notes'))
"

echo
echo "=== 7. 静态页面 ==="
for p in / /index.html /alerts.html /logs.html /app.js /alerts.js /logs.js /i18n.js /style.css; do
  printf '  %s  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B$p")" "$p"
done

echo
echo "=== 8. 零图片红线（三个页面）==="
for p in / /alerts.html /logs.html; do
  n=$(curl -s "$B$p" | grep -c '<img' || true)
  printf '  %s : <img> 数量 = %s\n' "$p" "$n"
done
