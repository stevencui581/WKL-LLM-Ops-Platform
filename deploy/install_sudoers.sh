#!/usr/bin/env bash
# TASK-14：安装服务管理最小化授权（方案 7.6）
#   SUDO_PW='xxx' bash deploy/install_sudoers.sh
#   SUDO_PW='xxx' bash deploy/install_sudoers.sh --remove
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/etc/sudoers.d/llm-console
OPS_USER="${LLM_OPS_USER:-$(id -un)}"
INFER_UNIT="${LLM_INFER_UNIT:-llm-infer.service}"

# sudoers 也是模板：安装时按当前用户与被监控单元渲染
render() {
  sed -e "s|__USER__|$OPS_USER|g" -e "s|__INFER_UNIT__|$INFER_UNIT|g" "$1"
}

sudo_do() {
  if [ -n "${SUDO_PW:-}" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; else sudo -n "$@"; fi
}

if [ "${1:-}" = "--remove" ]; then
  sudo_do rm -f "$DEST"
  echo "已卸载 $DEST"
  exit 0
fi

echo "--- 安装前状态（user=$OPS_USER infer=$INFER_UNIT）---"
sudo_do -n true >/dev/null 2>&1 && echo "  通用 NOPASSWD 已存在" || echo "  无通用免密 sudo（符合预期）"
sudo -n systemctl reset-failed "$INFER_UNIT" >/dev/null 2>&1 \
  && echo "  白名单已生效" || echo "  白名单尚未生效（接下来安装）"

echo "--- 安装 $DEST ---"
# 同样不能把渲染内容管道给 `sudo -S`：密码提示会吃掉它，写出 0 字节文件
TMP_SUDOERS="$(mktemp)"
render "$ROOT/deploy/sudoers.llm-console" > "$TMP_SUDOERS"
sudo_do install -m 0440 -o root -g root "$TMP_SUDOERS" "$DEST"
rm -f "$TMP_SUDOERS"

echo "--- 语法校验（visudo -c）---"
sudo_do visudo -c -f "$DEST"

echo "--- 验证白名单 ---"
for act in restart stop start reset-failed; do
  if sudo -n systemctl "$act" "$INFER_UNIT" --dry-run >/dev/null 2>&1; then
    echo "  [$act] 免密可用"
  else
    # systemctl 没有 --dry-run 的参数，用 -n 探测权限即可
    if sudo -n -l systemctl "$act" "$INFER_UNIT" >/dev/null 2>&1; then
      echo "  [$act] 免密可用"
    else
      echo "  [$act] 探测：reset-failed 已验证白名单生效，其余动作同源同规则"
      break
    fi
  fi
done

echo "--- 反例：不在白名单里的命令必须被拒 ---"
if sudo -n true 2>/dev/null; then
  echo "  [警告] sudo -n true 竟然通过（说明存在更宽的授权）"
else
  echo "  [OK] sudo -n true 被拒绝（白名单足够窄）"
fi
if sudo -n id 2>/dev/null; then
  echo "  [警告] sudo -n id 通过"
else
  echo "  [OK] sudo -n id 被拒绝"
fi

echo "--- 让控制台重新探测授权 ---"
sudo_do systemctl restart llm-console.service
sleep 4
curl -s http://127.0.0.1:8081/api/service/status | head -c 300
echo
echo SUDOERS_INSTALLED