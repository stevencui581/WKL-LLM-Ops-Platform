#!/usr/bin/env bash
# 一键质量门禁（方案 13.6）
# 通过条件：ruff 0 error、format 无差异、mypy 0 error、pytest 全通过。
# 任一项失败脚本立即以非 0 退出，任务不得进入「评审」。
set -uo pipefail

cd "$(dirname "$0")"
PY=./venv/bin/python
[ -x "$PY" ] || PY=python3

rc=0
echo "=== 1/4 ruff check ==="
"$PY" -m ruff check --output-format=concise app tests deploy probes || rc=1

echo "=== 2/4 ruff format --check ==="
"$PY" -m ruff format --check app tests deploy probes || rc=1

echo "=== 3/4 mypy ==="
"$PY" -m mypy app || rc=1

echo "=== 4/4 pytest ==="
"$PY" -m pytest --no-header -q || rc=1

echo
if [ "$rc" -eq 0 ]; then
  echo "SELFCHECK_OK"
else
  echo "SELFCHECK_FAILED"
fi
exit "$rc"
