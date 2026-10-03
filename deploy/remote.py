"""在目标服务器上执行命令（开发/部署用）。

    python deploy/remote.py "cd $WKL_ROOT && ./venv/bin/pytest -q"

连接参数来自环境变量或本地 ``deploy/host.env``（见 ``deploy/conn.py``），
仓库里不含任何真实主机与凭据。
"""

from __future__ import annotations

import os
import sys

import paramiko
from conn import Connection


def run(cmd: str, timeout: int = 1800) -> int:
    c = Connection.load()
    if not c.configured:
        print(c.hint(), file=sys.stderr)
        return 2
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(
        c.host,
        port=c.port,
        username=c.user,
        password=c.password,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        _, so, se = cli.exec_command(cmd, timeout=timeout)
        out = so.read().decode("utf-8", "replace")
        err = se.read().decode("utf-8", "replace")
        rc = so.channel.recv_exit_status()
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if err.strip():
            print("[stderr]", err, file=sys.stderr)
        return rc
    finally:
        cli.close()


if __name__ == "__main__":
    args = " ".join(sys.argv[1:])
    # 允许命令行里写 $WKL_ROOT，按当前连接配置展开
    args = args.replace("$WKL_ROOT", os.environ.get("WKL_ROOT") or Connection.load().root)
    sys.exit(run(args))
