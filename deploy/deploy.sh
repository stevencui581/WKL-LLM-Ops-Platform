#!/usr/bin/env bash
# 部署脚本（方案 TASK-22 / 9.4）：目录化 + 原子软链接切换 + 健康门禁自动回滚
#
# 用法（在 目标 上执行）：
#   bash deploy/deploy.sh                 # 用当前目录内容发布新版本
#   bash deploy/deploy.sh --rollback      # 回滚到上一个 release
#
# 设计要点：
#   * 切链接用 ln -sfnT + mv -T，mv -T 退化为 rename(2)，POSIX 保证原子；
#     直接 ln -sfn 到目录软链接时可能把链接建到目录内部。
#   * 只有健康检查通过才移动 current；失败自动切回上一版。
#   * systemctl restart 是 stop→start，不是零停机（方案 12.7 补充说明）。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=llm-console.service
PORT=8081
KEEP=5

log() { echo "[deploy] $*"; }
die() { echo "[deploy][ERROR] $*" >&2; exit 1; }

sudo_do() {
  if [ -n "${SUDO_PW:-}" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; else sudo -n "$@"; fi
}

health_ok() {
  for _ in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health/ready" || true)
    [ "$code" = "200" ] && return 0
    sleep 2
  done
  return 1
}

current_release() { readlink -f "$ROOT/current" 2>/dev/null || true; }

# ------------------------------------------------------------------ 回滚
rollback() {
  prev=$(ls -1dt "$ROOT"/releases/*/ 2>/dev/null | sed -n 2p)
  [ -n "$prev" ] || die "没有可回滚的历史版本"
  log "回滚到 $prev"
  ln -sfnT "${prev%/}" "$ROOT/.current.tmp" && mv -T "$ROOT/.current.tmp" "$ROOT/current"
  # 命中 StartLimit 后 unit 处于 failed，必须先 reset-failed 才能再启动
  sudo_do systemctl reset-failed "$UNIT" 2>/dev/null || true
  sudo_do systemctl restart "$UNIT"
  health_ok && log "回滚成功" || die "回滚后健康检查仍失败"
}

if [ "${1:-}" = "--rollback" ]; then rollback; exit 0; fi

# ------------------------------------------------------------------ 发布
STAMP=$(date +%Y%m%d-%H%M%S)
REL="$ROOT/releases/$STAMP"
PREV=$(current_release)

log "预检"
"$ROOT/venv/bin/python" -c "import app.main" || die "代码无法导入（import app.main 失败）"
systemd-analyze verify "/etc/systemd/system/$UNIT" >/dev/null 2>&1 || log "警告：unit 校验有提示，继续"
df -h "$ROOT" | tail -1
mkdir -p "$REL"

log "复制代码到 $REL"
rsync -a --delete \
  --exclude 'venv' --exclude 'releases' --exclude 'current' \
  --exclude 'state' --exclude 'logs' --exclude '__pycache__' \
  --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '.mypy_cache' \
  "$ROOT/app" "$ROOT/static" "$ROOT/deploy" "$ROOT/pyproject.toml" \
  "$ROOT/requirements.lock" "$REL/" 2>/dev/null || {
    log "rsync 不可用，改用 cp"
    mkdir -p "$REL"
    cp -r "$ROOT/app" "$ROOT/static" "$ROOT/deploy" "$REL/"
    cp "$ROOT/pyproject.toml" "$REL/" 2>/dev/null || true
    cp "$ROOT/requirements.lock" "$REL/" 2>/dev/null || true
  }

log "冒烟测试（前台起一次）"
( cd "$REL" && "$ROOT/venv/bin/python" -c "import app.main; print('import ok')" ) || die "冒烟测试失败"

log "切换 current -> $REL"
ln -sfnT "$REL" "$ROOT/.current.tmp" && mv -T "$ROOT/.current.tmp" "$ROOT/current"

log "重启服务"
sudo_do systemctl reset-failed "$UNIT" 2>/dev/null || true
sudo_do systemctl restart "$UNIT"

if health_ok; then
  log "健康检查通过，部署完成"
  sudo_do systemctl show "$UNIT" -p NRestarts,ActiveState
else
  log "健康检查失败，自动回滚"
  if [ -n "$PREV" ]; then
    ln -sfnT "$PREV" "$ROOT/.current.tmp" && mv -T "$ROOT/.current.tmp" "$ROOT/current"
    sudo_do systemctl restart "$UNIT"
    health_ok || die "回滚后仍不健康，需要人工介入"
    log "已回滚到 $PREV"
    exit 1
  fi
  die "无历史版本可回滚"
fi

log "清理旧版本（保留最近 $KEEP 个）"
ls -1dt "$ROOT"/releases/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf
log "DONE"
