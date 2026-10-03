#!/usr/bin/env bash
# =============================================================================
# WKL-LLM运维平台 —— 一键卸载 / One-command uninstall
#
#   bash uninstall.sh              # 保留配置与状态，仅停止并移除服务
#   bash uninstall.sh --purge      # 连同代码、虚拟环境、状态一起删除
#
# 中文：默认**不删代码**，只停服务并移除 systemd 单元，避免误删。
# English: by default the source tree is kept; only the service is removed.
# =============================================================================
set -uo pipefail

detect_lang() {
  if [ -n "${WKL_LANG:-}" ]; then echo "$WKL_LANG"; return; fi
  case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
    zh*|*zh_*) echo zh ;;
    *) echo en ;;
  esac
}
LANG_CODE="$(detect_lang)"
t() { if [ "$LANG_CODE" = "zh" ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

if [ -t 1 ]; then
  C_R="\033[31m"; C_G="\033[32m"; C_Y="\033[33m"; C_B="\033[36m"; C_0="\033[0m"; C_BOLD="\033[1m"
else
  C_R=""; C_G=""; C_Y=""; C_B=""; C_0=""; C_BOLD=""
fi
info() { printf "${C_B}==>${C_0} %s\n" "$*"; }
ok()   { printf "${C_G}  ✓${C_0} %s\n" "$*"; }
warn() { printf "${C_Y}  !${C_0} %s\n" "$*"; }
err()  { printf "${C_R}  ✗${C_0} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

PURGE=0
for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    -h|--help)
      cat <<EOF
$(t "用法" "Usage"): bash uninstall.sh [--purge]
  --purge   $(t "同时删除代码、虚拟环境与状态（不可恢复）" "also delete source, venv and state (irreversible)")
EOF
      exit 0 ;;
    *) die "$(t "未知参数" "unknown option"): $a" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
INSTALL_DIR="${WKL_INSTALL_DIR:-$SCRIPT_DIR}"

sudo_do() {
  if [ -n "${SUDO_PW:-}" ]; then printf '%s\n' "$SUDO_PW" | sudo -S -p '' "$@"; else sudo "$@"; fi
}

printf "\n${C_BOLD}%s${C_0}\n\n" "$(t "WKL-LLM运维平台 卸载程序" "WKL-LLM Ops Platform Uninstaller")"

# ---- 1. sudo 白名单 ----
if [ -f /etc/sudoers.d/llm-console ]; then
  info "$(t "移除 sudo 白名单" "removing the sudo allowlist")"
  [ -f "$INSTALL_DIR/deploy/install_sudoers.sh" ] \
    && bash "$INSTALL_DIR/deploy/install_sudoers.sh" --remove \
    || sudo_do rm -f /etc/sudoers.d/llm-console
  ok "/etc/sudoers.d/llm-console"
fi

# ---- 2. systemd 单元 ----
if systemctl list-unit-files 2>/dev/null | grep -q '^llm-console\.service'; then
  info "$(t "停止并移除 systemd 服务" "stopping and removing the systemd unit")"
  sudo_do systemctl disable --now llm-console.service 2>/dev/null || true
  sudo_do rm -f /etc/systemd/system/llm-console.service
  sudo_do systemctl daemon-reload
  ok "llm-console.service"
fi
for extra in llm-console-observe.service llm-console-observe.timer; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^$extra"; then
    sudo_do systemctl disable --now "$extra" 2>/dev/null || true
    sudo_do rm -f "/etc/systemd/system/$extra"
    ok "$extra"
  fi
done

# ---- 3. 可选：删除文件 ----
if [ "$PURGE" -eq 1 ]; then
  echo
  warn "$(t "--purge 将删除整个安装目录（含配置与历史状态）" \
          "--purge will delete the whole install directory (config + state)")"
  echo "  $INSTALL_DIR"
  printf "%s [y/N]: " "$(t "确认删除？" "confirm deletion?")"
  read -r ans </dev/tty 2>/dev/null || ans=""
  case "$ans" in
    y|Y|yes|YES)
      cd /tmp || true
      rm -rf "$INSTALL_DIR" && ok "$(t "已删除" "deleted") $INSTALL_DIR"
      ;;
    *) warn "$(t "已取消删除，仅移除服务" "deletion cancelled; only the service was removed")" ;;
  esac
else
  echo
  ok "$(t "代码与配置已保留" "source and config kept"): $INSTALL_DIR"
  echo "  $(t "如需彻底删除" "to remove everything"): bash uninstall.sh --purge"
fi

echo
echo "UNINSTALL_OK"
