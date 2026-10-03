#!/usr/bin/env bash
# 安装 /etc/systemd/system/llm-console.service 并启动
#
# 单元文件是**模板**（__USER__ / __ROOT__ / __INFER_UNIT__），
# 本脚本在安装时按当前环境渲染 —— 因此部署到任意用户/目录/推理单元都不用改文件。
#
# 需要 root；密码通过环境变量 SUDO_PW 传入。可覆盖：
#   LLM_OPS_USER     运行用户（默认：当前用户）
#   LLM_INFER_UNIT   被监控的推理服务单元（默认：llm-infer.service）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=llm-console.service
SUDO_PW="${SUDO_PW:-}"
OPS_USER="${LLM_OPS_USER:-$(id -un)}"
INFER_UNIT="${LLM_INFER_UNIT:-llm-infer.service}"

render() {
  sed -e "s|__USER__|$OPS_USER|g" \
      -e "s|__ROOT__|$ROOT|g" \
      -e "s|__INFER_UNIT__|$INFER_UNIT|g" "$1"
}

sudo_do() {
  if [ -n "$SUDO_PW" ]; then
    printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"
  else
    sudo -n "$@"
  fi
}

echo "--- prepare dirs ---"
mkdir -p "$ROOT/state" "$ROOT/logs" "$ROOT/releases"

echo "--- render & verify unit (user=$OPS_USER root=$ROOT infer=$INFER_UNIT) ---"
sudo_do mkdir -p /etc/systemd/system
# 注意：**不能**写成 `render ... | sudo_do tee ...`。
# `sudo -S` 从 stdin 读密码，管道里的渲染内容会被密码提示吃掉，
# 结果写出 0 字节文件，systemd 将其视为 masked（实测踩过的坑）。
# 正确做法：先渲染到临时文件，再 install 拷贝 —— 不占用 stdin。
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT
render "$ROOT/deploy/$UNIT" > "$TMP_UNIT"
sudo_do install -m 0644 -o root -g root "$TMP_UNIT" "/etc/systemd/system/$UNIT"
rm -f "$TMP_UNIT"
systemd-analyze verify "/etc/systemd/system/$UNIT" 2>&1 | head -20 || true

echo "--- daemon-reload & enable & restart ---"
sudo_do systemctl daemon-reload
sudo_do systemctl enable "$UNIT"
# 注意：enable --now 对已在运行的单元不会重启，必须显式 restart
sudo_do systemctl restart "$UNIT"
sleep 4

echo "--- status ---"
systemctl status "$UNIT" --no-pager 2>&1 | head -18 || true

echo "--- probes ---"
curl -s -o /dev/null -w 'live=%{http_code}\n'     http://127.0.0.1:8081/api/health/live    || true
curl -s -o /dev/null -w 'ready=%{http_code}\n'    http://127.0.0.1:8081/api/health/ready   || true
curl -s -o /dev/null -w 'overview=%{http_code}\n' http://127.0.0.1:8081/api/overview      || true
curl -s -o /dev/null -w 'index=%{http_code}\n'    http://127.0.0.1:8081/                   || true

echo "--- security score ---"
systemd-analyze security "$UNIT" --no-pager 2>&1 | tail -4 || true

echo INSTALL_DONE
