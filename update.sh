#!/usr/bin/env bash
# =============================================================================
# WKL-LLM运维平台 —— 一键升级 / One-command upgrade
#
# 中文：复制下面一行执行 / English: copy the single line below
#   curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/update.sh | bash
#
# 已 clone 仓库的话 / already cloned:
#   bash update.sh
#
# 做的事 / what it does:
#   1. 备份当前状态 / back up current state
#   2. 拉取最新代码 / pull the latest source
#   3. 更新依赖 / update dependencies
#   4. 自检 / self-check
#   5. 重启服务（若已注册）/ restart the service if installed
#
# 出错会自动回滚代码 / rolls the source back automatically on failure.
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
INSTALL_DIR="${WKL_INSTALL_DIR:-$SCRIPT_DIR}"
[ -f "$INSTALL_DIR/pyproject.toml" ] || die "$(t "未找到项目根目录（pyproject.toml）" "project root not found (pyproject.toml)")"
cd "$INSTALL_DIR" || die "$(t "无法进入项目目录" "cannot enter project directory")"

printf "\n${C_BOLD}%s${C_0}\n\n" "$(t "WKL-LLM运维平台 升级程序" "WKL-LLM Ops Platform Updater")"

VPY="$INSTALL_DIR/venv/bin/python"
VPIP="$INSTALL_DIR/venv/bin/pip"
[ -x "$VPY" ] || die "$(t "未找到虚拟环境，请先运行 install.sh" "virtualenv not found; run install.sh first")"

# ---- 记录当前版本，便于回滚时对照 ----
OLD_VERSION="$("$VPY" -c 'from app.config import Settings; print(Settings().product_version)' 2>/dev/null || echo unknown)"
OLD_REV="$(git rev-parse --short HEAD 2>/dev/null || echo none)"
info "$(t "当前版本" "current version"): $OLD_VERSION ${OLD_REV:+($OLD_REV)}"

# ================================================================ 1. 备份状态
info "$(t "1/5 备份运行状态" "1/5 Backing up runtime state")"
BACKUP_DIR="$INSTALL_DIR/.backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
for d in state logs .env; do
  [ -e "$INSTALL_DIR/$d" ] && cp -a "$INSTALL_DIR/$d" "$BACKUP_DIR/" 2>/dev/null || true
done
ok "$(t "已备份到" "backed up to") $BACKUP_DIR"

# ================================================================ 2. 拉取代码
info "$(t "2/5 拉取最新代码" "2/5 Fetching the latest source")"
PULLED=0
if [ -d "$INSTALL_DIR/.git" ]; then
  if git pull --ff-only 2>&1 | tail -3; then
    PULLED=1
    ok "$(t "代码已更新" "source updated")"
  else
    warn "$(t "git pull 失败（可能有本地改动），跳过" "git pull failed (local changes?); skipping")"
  fi
else
  warn "$(t "不是 git 仓库，跳过拉取" "not a git checkout; skipping")"
fi

ROLLBACK_NEEDED=0

# ================================================================ 3. 依赖
info "$(t "3/5 更新依赖" "3/5 Updating dependencies")"
if ! "$VPIP" install --quiet --upgrade -e . ; then
  err "$(t "依赖更新失败" "dependency update failed")"
  ROLLBACK_NEEDED=1
else
  ok "$(t "依赖已更新" "dependencies updated")"
fi

# ================================================================ 4. 自检
if [ "$ROLLBACK_NEEDED" -eq 0 ]; then
  info "$(t "4/5 升级自检" "4/5 Verifying the upgrade")"
  if "$VPY" -c 'import app.main' >/dev/null 2>&1; then
    NEW_VERSION="$("$VPY" -c 'from app.config import Settings; print(Settings().product_version)' 2>/dev/null || echo unknown)"
    ok "$(t "后端可正常导入，新版本" "backend imports cleanly, new version"): $NEW_VERSION"
  else
    err "$(t "后端导入失败" "backend import failed")"
    "$VPY" -c 'import app.main' || true
    ROLLBACK_NEEDED=1
  fi
fi

# ---- 失败回滚 ----
if [ "$ROLLBACK_NEEDED" -eq 1 ]; then
  err "$(t "升级失败，正在回滚" "upgrade failed, rolling back")"
  if [ "$PULLED" -eq 1 ] && [ "$OLD_REV" != "none" ]; then
    git reset --hard "$OLD_REV" && ok "$(t "代码已回滚到" "source rolled back to") $OLD_REV"
  fi
  [ -d "$BACKUP_DIR" ] && cp -a "$BACKUP_DIR/." "$INSTALL_DIR/" 2>/dev/null || true
  "$VPIP" install --quiet --upgrade -e . 2>/dev/null || true
  echo
  echo "$(t "备份保留在" "backup kept at"): $BACKUP_DIR"
  die "$(t "升级未完成，服务仍运行旧版本" "upgrade incomplete; the service still runs the old version")"
fi

# ================================================================ 5. 重启服务
info "$(t "5/5 重启控制台服务" "5/5 Restarting the console service")"
if systemctl list-unit-files 2>/dev/null | grep -q '^llm-console\.service'; then
  if [ -n "${SUDO_PW:-}" ]; then
    printf '%s\n' "$SUDO_PW" | sudo -S -p '' systemctl restart llm-console.service
  else
    sudo -n systemctl restart llm-console.service 2>/dev/null || {
      warn "$(t "无法免密重启，请手动执行：" "cannot restart without a password; run manually:")"
      echo "  sudo systemctl restart llm-console.service"
    }
  fi
  sleep 4
  if systemctl is-active --quiet llm-console.service; then
    ok "$(t "服务已重启并处于运行状态" "service restarted and active")"
  else
    err "$(t "服务未处于运行状态" "service is not active")"
    echo "  journalctl -u llm-console.service -n 50 --no-pager"
  fi
else
  warn "$(t "未注册 systemd 服务，请手动重启你的启动方式" \
          "no systemd unit installed; restart your own launch method")"
fi

printf "\n${C_G}${C_BOLD}%s${C_0}\n" "$(t "✓ 升级完成" "✓ Upgrade complete")"
echo
echo "$(t "版本" "version"): $OLD_VERSION → ${NEW_VERSION:-?}"
echo "$(t "备份" "backup"): $BACKUP_DIR"
echo "$(t "回滚" "rollback"): git reset --hard $OLD_REV && $VPIP install -e ."
echo
echo "UPDATE_OK"
