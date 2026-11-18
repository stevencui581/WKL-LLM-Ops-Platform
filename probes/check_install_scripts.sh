#!/usr/bin/env bash
# 一键安装脚本自检 / Self-check for the installer scripts
#   bash probes/check_install_scripts.sh
#
# 校验：
#   1. 三个脚本 bash 语法正确
#   2. 中英双语输出都能工作
#   3. --help 内容完整（含系统要求/依赖/示例）
#   4. 脚本不含 CRLF（CRLF 会让 bash 报 "invalid option name"）
#   5. 脚本是幂等的（--help 与参数解析不产生副作用）
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
pass=0
chk() { if [ "$2" = "1" ]; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

echo "=== 1. 语法检查 / syntax ==="
for f in install.sh update.sh uninstall.sh; do
  if [ ! -f "$f" ]; then chk "$f 存在" 0; continue; fi
  if bash -n "$f" 2>/dev/null; then chk "$f 语法正确" 1; else chk "$f 语法正确" 0; fi
done

echo
echo "=== 2. 行尾与 BOM / line endings ==="
for f in install.sh update.sh uninstall.sh; do
  if grep -q $'\r' "$f" 2>/dev/null; then chk "$f 无 CRLF" 0; else chk "$f 无 CRLF" 1; fi
  head -c 3 "$f" | od -An -tx1 | grep -q 'ef bb bf' && chk "$f 无 BOM" 0 || chk "$f 无 BOM" 1
  head -1 "$f" | grep -q '^#!/usr/bin/env bash' && chk "$f shebang 正确" 1 || chk "$f shebang 正确" 0
done

echo
echo "=== 3. 双语 --help / bilingual help ==="
ZH="$(WKL_LANG=zh bash install.sh --help 2>&1)"
EN="$(WKL_LANG=en bash install.sh --help 2>&1)"
echo "$ZH" | grep -q '一键安装脚本' && chk "中文 help 正常" 1 || chk "中文 help 正常" 0
echo "$EN" | grep -q 'one-command installer' && chk "英文 help 正常" 1 || chk "英文 help 正常" 0

echo
echo "=== 4. help 内容完整性 / help completeness ==="
# 注意：grep -E 下 | 是「或」，写成 \| 反而变成字面量匹配（曾经的测试 bug）
for kw in 'Usage|用法' 'port' 'infer-unit' 'infer-url' 'install-service' 'skip-deps' 'SUDO_PW'; do
  if echo "$EN" | grep -qE "$kw"; then chk "help 含 $kw" 1; else chk "help 含 $kw" 0; fi
done

echo
echo "=== 5. 三种推理框架示例都在 help 里 / framework examples ==="
for kw in 'llama-server' 'ollama' 'vllm' 'sglang'; do
  if echo "$EN" | grep -qiE "$kw"; then chk "help 提到 $kw" 1; else chk "help 提到 $kw" 0; fi
done

echo
echo "=== 6. 参数解析无副作用 / no side effects ==="
if WKL_LANG=en bash install.sh --unknown-flag >/dev/null 2>&1; then
  chk "未知参数应报错退出" 0
else
  chk "未知参数应报错退出" 1
fi
if WKL_LANG=en bash uninstall.sh --help >/dev/null 2>&1; then
  chk "uninstall --help 正常" 1
else
  chk "uninstall --help 正常" 0
fi

echo
echo "=== 7. venv 复用防御 / venv reuse defence ==="
# 真实事故（v0.6.1）：Ubuntu 26.04 + Python 3.14 没装 python3.14-venv 时，
# ``python3 -m venv`` 会留下「有 python、没 pip」的残缺目录；install.sh 原先
# 只判断目录存在就"复用"，随后 ``venv/bin/pip`` 不存在 —— 直接报
#   venv/bin/pip: No such file or directory → dependency installation failed
# 这组静态检查保证三道闸不会被改回去。
if grep -qF 'import venv, ensurepip' install.sh; then
  chk "依赖检查含 ensurepip（不只 import venv）" 1
else
  chk "依赖检查含 ensurepip（不只 import venv）" 0
fi
if grep -qF 'bin/python" -m pip --version' install.sh; then
  chk "复用 venv 前验证 pip 可用" 1
else
  chk "复用 venv 前验证 pip 可用" 0
fi
if grep -qF 'VPIP' install.sh; then
  chk "不直接调用 venv/bin/pip（统一 python -m pip）" 0
else
  chk "不直接调用 venv/bin/pip（统一 python -m pip）" 1
fi
if grep -qF 'python${PY_VER}-venv' install.sh; then
  chk "缺失提示按实际 Python 版本给包名" 1
else
  chk "缺失提示按实际 Python 版本给包名" 0
fi
if grep -qF '已有虚拟环境不完整' install.sh; then
  chk "残缺 venv 会重建而不是复用" 1
else
  chk "残缺 venv 会重建而不是复用" 0
fi

echo
echo "pass=$pass fail=$fail"
if [ "$fail" -eq 0 ]; then echo "INSTALL_SCRIPTS_OK"; exit 0; fi
echo "INSTALL_SCRIPTS_FAILED"; exit 1
