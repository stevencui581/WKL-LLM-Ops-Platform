#!/usr/bin/env bash
# 干净的 sudo 白名单验证：先清空凭据缓存，再逐条探测
# 注意：sudo 的 -n 会使用已缓存的凭据，刚用密码认证过会得到假阳性，
# 因此必须先 sudo -k。
set -uo pipefail

echo "--- 路径 ---"
which systemctl
which sudo

echo "--- /etc/sudoers.d ---"
ls -l /etc/sudoers.d/

echo "--- 清空 sudo 凭据缓存 ---"
sudo -k 2>/dev/null || true

echo "--- 白名单内（应全部 rc=0）---"
for act in restart stop start reset-failed; do
  sudo -n systemctl "$act" llm-infer.service --dry-run >/dev/null 2>&1
  rc=$?
  # systemctl 无 --dry-run，rc 非 0 不代表无权限；用 -n 执行真实 reset-failed 最可靠
  printf '  %-13s probe_rc=%s\n' "$act" "$rc"
done

echo "--- 真实执行 reset-failed（白名单内、对运行中单元是空操作）---"
sudo -k 2>/dev/null || true
sudo -n systemctl reset-failed llm-infer.service
echo "  reset-failed rc=$?"

echo "--- 白名单外（应被拒绝，rc!=0）---"
sudo -k 2>/dev/null || true
sudo -n true >/dev/null 2>&1; echo "  sudo -n true  rc=$?"
sudo -k 2>/dev/null || true
sudo -n id   >/dev/null 2>&1; echo "  sudo -n id    rc=$?"
sudo -k 2>/dev/null || true
sudo -n systemctl restart nginx.service >/dev/null 2>&1; echo "  restart nginx rc=$?"
sudo -k 2>/dev/null || true
sudo -n systemctl stop llama-server.service >/dev/null 2>&1; echo "  stop 其他单元 rc=$?"
