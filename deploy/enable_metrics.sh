#!/usr/bin/env bash
# TASK-01 + TASK-02：为 llama-server 启用 --metrics（L3 变更，需维护窗口）
#
# 用法：
#   SUDO_PW='xxx' bash deploy/enable_metrics.sh            # 记录基线
#   SUDO_PW='xxx' bash deploy/enable_metrics.sh --apply    # 执行变更
#   SUDO_PW='xxx' bash deploy/enable_metrics.sh --rollback # 回滚
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_PATH=/etc/systemd/system/llm-infer.service
UNIT=llm-infer.service
STATE="$ROOT/state"
STAMP=$(date +%Y%m%d-%H%M%S)

sudo_do() {
  if [ -n "${SUDO_PW:-}" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; else sudo -n "$@"; fi
}

preflight() {
  echo "--- 变更前基线 ---"
  mkdir -p "$STATE"
  curl -s -o /dev/null -w '  /health  = %{http_code}\n' http://127.0.0.1:8080/health
  curl -s -o /dev/null -w '  /metrics = %{http_code}  (期望 501)\n' http://127.0.0.1:8080/metrics
  curl -s http://127.0.0.1:8080/slots | head -c 120; echo
  curl -s http://127.0.0.1:8080/props | python3 -c "
import json,sys
p=json.load(sys.stdin)
print('  total_slots =', p.get('total_slots'), ' n_ctx =', p.get('default_generation_settings',{}).get('n_ctx'))
print('  endpoint_metrics =', p.get('endpoint_metrics'))
" 2>/dev/null || true
  echo "  --- 推理吞吐基线（3 轮）---"
  "$ROOT/venv/bin/python" "$ROOT/deploy/bench_infer.py" --label before
}

do_apply() {
  echo "--- 备份 unit ---"
  BACKUP="${UNIT_PATH}.bak.v41-${STAMP}"
  sudo_do cp -n "$UNIT_PATH" "$BACKUP" && echo "  备份: $BACKUP"

  if grep -q -- '--metrics' "$UNIT_PATH"; then
    echo "  已包含 --metrics，无需修改"
  else
    echo "--- 追加 --metrics 到 ExecStart ---"
    sudo_do sed -i '/^ExecStart=/ s/$/ --metrics/' "$UNIT_PATH"
    echo "  修改后 ExecStart:"
    grep '^ExecStart=' "$UNIT_PATH" | sed 's/^/    /'
  fi

  echo "--- daemon-reload + restart ---"
  sudo_do systemctl daemon-reload
  sudo_do systemctl restart "$UNIT"
  echo "  已发起重启，等待模型加载..."
}

wait_ready() {
  local deadline=$((SECONDS + 300))
  while [ $SECONDS -lt $deadline ]; do
    code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/metrics || true)
    health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health || true)
    printf '  t+%3ds  health=%s  metrics=%s\n' "$((SECONDS))" "$health" "$code"
    if [ "$code" = "200" ]; then
      echo "  /metrics 已就绪"
      return 0
    fi
    sleep 10
  done
  echo "  超时：300 秒内 /metrics 未就绪" >&2
  return 1
}

post_verify() {
  echo "--- 变更后验证 ---"
  curl -s -o /dev/null -w '  /metrics = %{http_code}\n' http://127.0.0.1:8080/metrics
  echo "  指标样本:"
  curl -s http://127.0.0.1:8080/metrics | grep -E '^llamacpp:(requests_processing|requests_deferred|tokens_predicted_total|spec_decode_num_accepted_tokens_total)' | sed 's/^/    /'
  curl -s http://127.0.0.1:8080/slots  | python3 -c "
import json,sys
d=json.load(sys.stdin); print('  /slots 槽位数 =', len(d))
" 2>/dev/null || true
  curl -s http://127.0.0.1:8080/props  | python3 -c "
import json,sys
p=json.load(sys.stdin)
print('  endpoint_metrics =', p.get('endpoint_metrics'), ' n_ctx =', p.get('default_generation_settings',{}).get('n_ctx'))
" 2>/dev/null || true
  echo "  --- 推理吞吐复测（3 轮）---"
  "$ROOT/venv/bin/python" "$ROOT/deploy/bench_infer.py" --label after --compare
}

do_rollback() {
  LATEST=$(ls -1t ${UNIT_PATH}.bak.v41-* 2>/dev/null | head -1)
  [ -n "$LATEST" ] || { echo "找不到备份，无法回滚" >&2; exit 1; }
  echo "--- 回滚 unit（$LATEST）---"
  sudo_do cp -f "$LATEST" "$UNIT_PATH"
  sudo_do systemctl daemon-reload
  sudo_do systemctl restart "$UNIT"
  for _ in $(seq 1 30); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health || true)" = "200" ] && { echo "回滚后服务已恢复"; exit 0; }
    sleep 10
  done
  echo "回滚后健康检查失败，需要人工介入" >&2
  exit 1
}

case "${1:-}" in
  --apply)    preflight; do_apply; wait_ready && post_verify ;;
  --rollback) do_rollback ;;
  *)          preflight ;;
esac
