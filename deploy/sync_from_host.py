"""把 目标服务器上的代码同步回本地（保持本地与生产一致）。

用法：
    python deploy/sync_from_host.py           # 同步 app/ tests/ static/ deploy/
    python deploy/sync_from_host.py --list    # 只列出远端文件
"""

from __future__ import annotations

import argparse
import os
import posixpath
import stat
import sys

import paramiko
from conn import Connection

CONN = Connection.load()
REMOTE_ROOT = CONN.root
LOCAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 必须与 upload.py 的 INCLUDE_DIRS 保持一致！
#: v0.4.4 踩过的坑：这里漏了 probes/tools，于是在 目标 上跑的 `ruff --fix`
#: 无法回传本地 —— 下次 upload 又把未修复的版本覆盖回去，
#: 表现为"本地与远端来回分叉、同一个 lint 错误反复出现"。
DIRS = ("app", "tests", "static", "deploy", "probes", "tools")
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(
        CONN.host,
        port=CONN.port,
        username=CONN.user,
        password=CONN.password,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = cli.open_sftp()
    pulled = 0

    def walk(remote_dir: str) -> None:
        nonlocal pulled
        for entry in sftp.listdir_attr(remote_dir):
            if entry.filename in SKIP_PARTS:
                continue
            rpath = posixpath.join(remote_dir, entry.filename)
            rel = os.path.relpath(rpath, REMOTE_ROOT).replace("/", os.sep)
            if stat.S_ISDIR(entry.st_mode or 0):
                walk(rpath)
                continue
            if args.list:
                print(rel)
                continue
            lpath = os.path.join(LOCAL_ROOT, rel)
            os.makedirs(os.path.dirname(lpath), exist_ok=True)
            sftp.get(rpath, lpath)
            pulled += 1

    for d in DIRS:
        try:
            walk(posixpath.join(REMOTE_ROOT, d))
        except OSError as exc:
            print(f"skip {d}: {exc}", file=sys.stderr)

    sftp.close()
    cli.close()
    print("listed remote files" if args.list else f"synced {pulled} files from 253")
    return 0


if __name__ == "__main__":
    sys.exit(main())
