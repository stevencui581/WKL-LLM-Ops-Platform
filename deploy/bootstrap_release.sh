#!/usr/bin/env bash
# 首次建立 releases/<stamp> + current 软链接（方案 9.4 目录约定）
# 之后所有发布都走 deploy.sh，不再需要本脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP=$(date +%Y%m%d-%H%M%S)
REL="$ROOT/releases/$STAMP"

mkdir -p "$REL" "$ROOT/releases" "$ROOT/state" "$ROOT/logs"

echo "--- 建立初始 release: $REL ---"
cp -r "$ROOT/app" "$ROOT/static" "$ROOT/deploy" "$REL/"
cp "$ROOT/pyproject.toml" "$REL/" 2>/dev/null || true
cp "$ROOT/requirements.lock" "$REL/" 2>/dev/null || true
cp "$ROOT/selfcheck.sh" "$ROOT/conftest.py" "$REL/" 2>/dev/null || true
[ -d "$ROOT/tests" ] && cp -r "$ROOT/tests" "$REL/"

echo "--- 切换 current（ln -sfnT + mv -T，rename(2) 原子）---"
ln -sfnT "$REL" "$ROOT/.current.tmp" && mv -T "$ROOT/.current.tmp" "$ROOT/current"
readlink -f "$ROOT/current"

echo "--- 校验 release 可导入 ---"
cd "$ROOT/current" && "$ROOT/venv/bin/python" -c "import app.main; print('release import ok')"

echo BOOTSTRAP_OK
