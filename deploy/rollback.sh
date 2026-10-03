#!/usr/bin/env bash
# 回滚脚本（方案 TASK-22 / 9.4）—— 分钟级恢复到上一个 release
#
#   bash deploy/rollback.sh            # 回到上一个版本
#   bash deploy/rollback.sh --list     # 列出所有可回滚版本
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=llm-console.service
PORT=8081

sudo_do() {
  if [ -n "${SUDO_PW:-}" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; else sudo -n "$@"; fi
}

list_releases() {
  echo "可用版本（新 -> 旧）："
  ls -1dt "$ROOT"/releases/*/ 2>/dev/null | nl -w2 -s'. '
  echo "当前指向：$(readlink -f "$ROOT/current" 2>/dev/null || echo 无)"
}

if [ "${1:-}" = "--list" ]; then list_releases; exit 0; fi

CUR=$(readlink -f "$ROOT/current" 2>/dev/null || true)
PREV=$(ls -1dt "$ROOT"/releases/*/ 2>/dev/null | while read -r d; do
  d="${d%/}"
  [ "$d" != "$CUR" ] && echo "$d" && break
done)

if [ -z "$PREV" ]; then
  echo "没有可回滚的历史版本" >&2
  list_releases >&2
  exit 1
fi

echo "[rollback] 当前：${CUR:-无}"
echo "[rollback] 目标：$PREV"

ln -sfnT "$PREV" "$ROOT/.current.tmp" && mv -T "$ROOT/.current.tmp" "$ROOT/current" \
  || { echo "切换软链接失败" >&2; exit 1; }

# 命中 StartLimit 后 unit 处于 failed，必须先 reset-failed
sudo_do systemctl reset-failed "$UNIT" 2>/dev/null || true
sudo_do systemctl restart "$UNIT"

for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health/ready" || true)
  if [ "$code" = "200" ]; then
    echo "[rollback] 成功，耗时约 $((i * 2)) 秒"
    systemctl status "$UNIT" --no-pager | head -6
    exit 0
  fi
  sleep 2
done

echo "[rollback] 回滚后健康检查失败，需要人工介入" >&2
exit 1
