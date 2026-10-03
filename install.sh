#!/usr/bin/env bash
# =============================================================================
# WKL-LLM运维平台 —— 一键安装脚本 / One-command installer
#
# 中文：直接把下面这一行复制到终端执行即可（无需其它准备）
#   curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
#
# English: copy the single line below into your terminal
#   curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
#
# 已经 clone 了仓库的话 / already cloned:
#   bash install.sh
#
# 脚本做的事 / what it does:
#   1. 检查操作系统与依赖 / check OS and dependencies
#   2. 创建 Python 虚拟环境 / create a Python virtualenv
#   3. 安装依赖 / install dependencies
#   4. 生成 .env 配置 / generate .env
#   5. 自检 / run self-check
#   6. （可选）注册 systemd 服务 / optionally install a systemd unit
#
# 幂等：重复执行不会破坏已有安装 / idempotent: safe to re-run.
# =============================================================================
set -uo pipefail

# ----------------------------------------------------------------- 语言
# 自动判断语言：LANG/LC_ALL 含 zh 用中文，否则英文。可用 WKL_LANG=zh|en 强制。
detect_lang() {
  if [ -n "${WKL_LANG:-}" ]; then echo "$WKL_LANG"; return; fi
  case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
    zh*|*zh_*) echo zh ;;
    *) echo en ;;
  esac
}
LANG_CODE="$(detect_lang)"

# 双语输出：t "中文" "English"
t() {
  if [ "$LANG_CODE" = "zh" ]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}

# ----------------------------------------------------------------- 颜色
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

# ----------------------------------------------------------------- 参数
PORT="${WKL_PORT:-8081}"
INFER_UNIT="${WKL_INFER_UNIT:-}"
INFER_URL="${WKL_INFER_URL:-}"
INSTALL_SERVICE=0
SKIP_DEPS=0
NON_INTERACTIVE=0

usage() {
  cat <<EOF
$(t "WKL-LLM运维平台 一键安装脚本" "WKL-LLM Ops Platform — one-command installer")

$(t "用法" "Usage"):
  bash install.sh [选项 / options]

$(t "选项" "Options"):
  --port <端口>            $(t "控制台监听端口（默认 8081）" "console port (default 8081)")
  --infer-unit <单元名>    $(t "被监控的推理服务 systemd 单元" "systemd unit of the inference service")
  --infer-url <URL>        $(t "推理服务 HTTP 地址" "inference service base URL")
  --install-service        $(t "同时注册 systemd 服务（需要 sudo）" "also install a systemd unit (needs sudo)")
  --skip-deps              $(t "跳过依赖安装（离线环境）" "skip dependency install (offline)")
  -y, --yes                $(t "非交互模式，全部用默认值" "non-interactive, accept defaults")
  -h, --help               $(t "显示本帮助" "show this help")

$(t "环境变量" "Environment"):
  WKL_LANG=zh|en           $(t "强制输出语言" "force output language")
  WKL_PORT                 $(t "等同 --port" "same as --port")
  WKL_INFER_UNIT           $(t "等同 --infer-unit" "same as --infer-unit")
  WKL_INFER_URL            $(t "等同 --infer-url" "same as --infer-url")
  SUDO_PW                  $(t "sudo 密码（需要时）" "sudo password when required")

$(t "示例" "Examples"):
  # llama.cpp（默认端口 8080）/ llama.cpp (default port 8080)
  bash install.sh --infer-unit llama-server.service

  # Ollama（默认端口 11434）/ Ollama (default port 11434)
  bash install.sh --infer-unit ollama.service --infer-url http://127.0.0.1:11434

  # vLLM（默认端口 8000）/ vLLM (default port 8000)
  bash install.sh --infer-unit vllm.service --infer-url http://127.0.0.1:8000

  # SGLang（默认端口 30000）/ SGLang (default port 30000)
  bash install.sh --infer-unit sglang.service --infer-url http://127.0.0.1:30000

  # 一并注册为 systemd 服务（开机自启）/ also install a systemd unit
  bash install.sh --infer-unit llama-server.service --install-service -y

$(t "推荐的推理服务默认端口" "Default ports by framework"):
  llama.cpp  8080     Ollama  11434     vLLM  8000     SGLang  30000
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2 ;;
    --infer-unit) INFER_UNIT="${2:-}"; shift 2 ;;
    --infer-url) INFER_URL="${2:-}"; shift 2 ;;
    --install-service) INSTALL_SERVICE=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    -y|--yes) NON_INTERACTIVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "$(t "未知参数" "unknown option"): $1" ;;
  esac
done

# ----------------------------------------------------------------- 工作目录
# 支持两种运行方式：
#   1) 在已 clone 的仓库里执行        → 就地安装
#   2) curl | bash（无仓库）          → 先下载到 $HOME/WKL-LLM-Ops-Platform
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
REPO_URL="${WKL_REPO_URL:-https://github.com/stevencui581/WKL-LLM-Ops-Platform.git}"
INSTALL_DIR="${WKL_INSTALL_DIR:-}"

if [ -z "$INSTALL_DIR" ]; then
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
  else
    INSTALL_DIR="$HOME/WKL-LLM-Ops-Platform"
  fi
fi

printf "\n${C_BOLD}%s${C_0}\n" "$(t "WKL-LLM运维平台 安装程序" "WKL-LLM Ops Platform Installer")"
printf "%s\n\n" "$(t "目标目录 / target: $INSTALL_DIR" "target directory: $INSTALL_DIR")"

# ================================================================ 1. 操作系统
info "$(t "1/6 检查操作系统" "1/6 Checking operating system")"

OS_ID=""; OS_VER=""; OS_PRETTY=""
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-}"; OS_VER="${VERSION_ID:-}"; OS_PRETTY="${PRETTY_NAME:-$ID $VERSION_ID}"
fi

if [ "$(uname -s)" != "Linux" ]; then
  err "$(t "本平台只支持 Linux（需要 systemd 与 journald）" "Linux only (systemd + journald required)")"
  err "$(t "当前系统" "current"): $(uname -s)"
  die "$(t "安装中止" "installation aborted")"
fi
ok "Linux ✓"

case "$OS_ID" in
  ubuntu|debian|linuxmint|pop) ok "$OS_PRETTY ✓" ;;
  rhel|centos|rocky|almalinux|fedora|openeuler|kylin|uos)
      ok "$OS_PRETTY ✓"; PKG_FAMILY=rpm ;;
  "")
      warn "$(t "无法识别发行版，继续尝试" "could not detect the distribution; continuing")"
      OS_PRETTY="unknown" ;;
  *)
      warn "$(t "未在测试列表中的发行版：$OS_PRETTY（通常会正常工作）" \
              "untested distribution: $OS_PRETTY (usually works)")" ;;
esac

# systemd 必需
if ! command -v systemctl >/dev/null 2>&1; then
  err "$(t "未找到 systemctl —— 本平台依赖 systemd 读取服务状态与日志" \
          "systemctl not found — this platform relies on systemd for service state and logs")"
  die "$(t "安装中止" "installation aborted")"
fi
ok "systemd ✓"

# ================================================================ 2. 依赖
info "$(t "2/6 检查依赖" "2/6 Checking dependencies")"

# ---- Python 3.12+ ----
PY=""
for cand in python3.13 python3.12 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    v="$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    major="${v%%.*}"; minor="${v##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 12 ]; then PY="$cand"; PY_VER="$v"; break; fi
    [ -z "${PY_VER:-}" ] && PY_VER="$v"
  fi
done

if [ -z "$PY" ]; then
  err "$(t "需要 Python 3.12 或更高" "Python 3.12 or newer is required")"
  [ -n "${PY_VER:-}" ] && err "$(t "检测到" "detected"): Python $PY_VER"
  echo
  echo "$(t "安装 Python 3.12 的方法：" "How to install Python 3.12:")"
  case "$OS_ID" in
    ubuntu|debian|linuxmint|pop)
      echo "  sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip" ;;
    rhel|centos|rocky|almalinux|fedora|openeuler|kylin|uos)
      echo "  sudo dnf install -y python3.12 python3.12-pip" ;;
    *)
      echo "  https://www.python.org/downloads/" ;;
  esac
  die "$(t "安装中止" "installation aborted")"
fi
ok "Python $PY_VER ($(command -v "$PY"))"
PYBIN="$PY"

# ---- venv 模块 ----
if ! "$PYBIN" -c 'import venv' >/dev/null 2>&1; then
  err "$(t "Python venv 模块缺失" "the Python venv module is missing")"
  case "$OS_ID" in
    ubuntu|debian|linuxmint|pop)
      echo "  sudo apt install -y python3.12-venv" ;;
    *)
      echo "  $(t "请安装对应发行版的 python3-venv 包" "install the python3-venv package for your distribution")" ;;
  esac
  die "$(t "安装中止" "installation aborted")"
fi
ok "venv ✓"

# ---- journald 读取权限 ----
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qE '^(systemd-journal|adm)$'; then
  ok "$(t "可读取 journald 日志" "journald access ✓")"
else
  warn "$(t "当前用户不在 systemd-journal / adm 组，日志面板可能为空" \
          "current user is not in systemd-journal/adm; the log panel may be empty")"
  warn "  sudo usermod -aG systemd-journal $USER  &&  $(t "重新登录后生效" "re-login to apply")"
fi

# ---- 推理服务（可选提示）----
if [ -z "$INFER_UNIT" ] && [ "$NON_INTERACTIVE" -eq 0 ]; then
  DETECTED="$(systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
    | grep -oE '[A-Za-z0-9_.@-]+\.service' \
    | grep -iE 'llama|ollama|vllm|sglang|tgi|infer' | head -1 || true)"
  if [ -n "$DETECTED" ]; then
    printf "%s [%s]: " "$(t "检测到推理服务，被监控单元名" "detected inference service, unit name")" "$DETECTED"
    read -r ans </dev/tty 2>/dev/null || ans=""
    INFER_UNIT="${ans:-$DETECTED}"
  fi
fi

# ================================================================ 3. 获取代码
info "$(t "3/6 准备代码" "3/6 Preparing the source tree")"

if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
  ok "$(t "使用已有代码" "using existing tree"): $INSTALL_DIR"
else
  command -v git >/dev/null 2>&1 || die "$(t "需要 git 才能下载代码" "git is required to fetch the source")"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  info "$(t "克隆仓库到" "cloning into") $INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" \
    || die "$(t "克隆失败，请检查网络或改用 git clone 后执行 bash install.sh" \
             "clone failed; check your network or use git clone + bash install.sh")"
  ok "$(t "代码已就绪" "source ready")"
fi
cd "$INSTALL_DIR" || die "$(t "无法进入" "cannot enter") $INSTALL_DIR"

# ================================================================ 4. 安装依赖
info "$(t "4/6 创建虚拟环境并安装依赖" "4/6 Creating virtualenv and installing dependencies")"

VENV_DIR="$INSTALL_DIR/venv"
if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
  ok "$(t "复用已有虚拟环境" "reusing existing virtualenv")"
else
  "$PYBIN" -m venv "$VENV_DIR" || die "$(t "创建虚拟环境失败" "failed to create the virtualenv")"
  ok "$(t "虚拟环境已创建" "virtualenv created"): $VENV_DIR"
fi

VPY="$VENV_DIR/bin/python"
VPIP="$VENV_DIR/bin/pip"

if [ "$SKIP_DEPS" -eq 1 ]; then
  warn "$(t "已跳过依赖安装（--skip-deps）" "dependency install skipped (--skip-deps)")"
else
  info "$(t "升级 pip" "upgrading pip")"
  "$VPY" -m pip install --quiet --upgrade pip || warn "$(t "pip 升级失败，继续" "pip upgrade failed; continuing")"

  info "$(t "安装运行依赖（联网，约 1-2 分钟）" "installing runtime dependencies (online, ~1-2 min)")"
  if ! "$VPIP" install --quiet -e . ; then
    err "$(t "依赖安装失败" "dependency installation failed")"
    echo "$(t "常见原因与处理：" "common causes and fixes:")"
    echo "  - $(t "网络问题：配置镜像后重试" "network: configure a mirror and retry")"
    echo "      pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple"
    echo "  - $(t "缺少编译工具" "missing build tools"): sudo apt install -y build-essential python3-dev"
    die "$(t "安装中止" "installation aborted")"
  fi
  ok "$(t "运行依赖已安装" "runtime dependencies installed")"

  # 开发依赖为可选，失败不影响使用
  if [ "${WKL_WITH_DEV:-0}" = "1" ]; then
    info "$(t "安装开发依赖" "installing dev dependencies")"
    "$VPIP" install --quiet -e '.[dev]' || warn "$(t "开发依赖安装失败（不影响使用）" "dev deps failed (non-fatal)")"
  fi
fi

# ================================================================ 5. 配置
info "$(t "5/6 生成配置" "5/6 Writing configuration")"

ENV_FILE="$INSTALL_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  ok "$(t "已存在 .env，保留不覆盖" "existing .env kept")"
else
  {
    echo "# WKL-LLM运维平台 / WKL-LLM Ops Platform"
    echo "# $(t "由 install.sh 生成" "generated by install.sh") $(date -Iseconds 2>/dev/null || date)"
    echo
    if [ -n "$INFER_UNIT" ]; then
      echo "LLMCONSOLE_LLAMA_UNIT=$INFER_UNIT"
    else
      echo "# LLMCONSOLE_LLAMA_UNIT=llama-server.service"
    fi
    if [ -n "$INFER_URL" ]; then
      echo "LLMCONSOLE_LLAMA_BASE_URL=$INFER_URL"
    else
      echo "# $(t "llama.cpp=8080 / Ollama=11434 / vLLM=8000 / SGLang=30000" \
                    "llama.cpp=8080 / Ollama=11434 / vLLM=8000 / SGLang=30000")"
      echo "# LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080"
    fi
    echo "LLMCONSOLE_PORT=$PORT"
    echo "LLMCONSOLE_LOG_LEVEL=INFO"
  } > "$ENV_FILE"
  ok "$(t "已写入" "wrote") $ENV_FILE"
fi

if [ -z "$INFER_UNIT" ]; then
  warn "$(t "未指定推理服务单元名，请编辑 .env 里的 LLMCONSOLE_LLAMA_UNIT" \
          "inference unit not set; edit LLMCONSOLE_LLAMA_UNIT in .env")"
fi

# ================================================================ 6. 自检
info "$(t "6/6 安装自检" "6/6 Verifying the installation")"

if "$VPY" -c 'import app.main' >/dev/null 2>&1; then
  ok "$(t "后端可正常导入" "backend imports cleanly")"
else
  err "$(t "后端导入失败" "backend import failed")"
  "$VPY" -c 'import app.main' || true
  die "$(t "安装未完成" "installation incomplete")"
fi

if "$VPY" -c 'from app.config import Settings; s=Settings(); print(s.product_version)' >/dev/null 2>&1; then
  VER="$("$VPY" -c 'from app.config import Settings; print(Settings().product_version)')"
  ok "$(t "配置可读取，版本" "config readable, version") $VER"
fi

printf "\n${C_G}${C_BOLD}%s${C_0}\n" "$(t "✓ 安装完成" "✓ Installation complete")"
echo
echo "$(t "启动控制台：" "Start the console:")"
echo
echo "  cd $INSTALL_DIR"
echo "  ./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
echo
if [ "$PORT" = "8081" ]; then
  echo "$(t "然后浏览器打开" "then open"): http://<$(t "服务器地址" "server-ip")>:8081"
else
  echo "$(t "然后浏览器打开" "then open"): http://<$(t "服务器地址" "server-ip")>:$PORT"
fi
echo

# ================================================================ 可选：systemd
if [ "$INSTALL_SERVICE" -eq 1 ]; then
  info "$(t "注册 systemd 服务（需要 sudo）" "installing the systemd unit (needs sudo)")"
  if [ -z "$INFER_UNIT" ]; then
    warn "$(t "未指定 --infer-unit，使用默认 llm-infer.service" \
            "no --infer-unit given; defaulting to llm-infer.service")"
  fi
  LLM_INFER_UNIT="${INFER_UNIT:-llm-infer.service}" \
  LLM_OPS_USER="$(id -un)" \
    bash deploy/install_service.sh
  echo
  echo "$(t "查看状态" "check status"):  systemctl status llm-console.service"
  echo "$(t "查看日志" "check logs"):    journalctl -u llm-console.service -f"
else
  echo "$(t "要注册为 systemd 服务（开机自启）：" "to run as a systemd service (start on boot):")"
  echo "  cd $INSTALL_DIR && bash install.sh --install-service$( [ -n "$INFER_UNIT" ] && echo " --infer-unit $INFER_UNIT" )"
  echo
  echo "$(t "或直接使用部署脚本：" "or use the deploy script directly:")"
  echo "  LLM_INFER_UNIT=${INFER_UNIT:-<$(t "你的推理单元" "your-infer-unit")>} SUDO_PW='<$(t "密码" "password")>' bash deploy/install_service.sh"
fi

echo
echo "$(t "文档" "Documentation"): https://github.com/stevencui581/WKL-LLM-Ops-Platform/tree/main/docs"
echo "$(t "遇到问题" "Troubleshooting"): docs/TROUBLESHOOTING.md"
echo
echo "INSTALL_OK"
