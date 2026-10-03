"""预检：上传 → 在 目标 上格式化+门禁 → 同步回本地（v0.4.4）。

    python deploy/preflight.py            # 完整流程
    python deploy/preflight.py --check    # 只上传+门禁，不回传

**为什么需要它**（v0.4.4 踩过的坑）：
    ruff / mypy 只装在 目标 的 venv 里，本地没有 —— 于是"格式化"发生在远端。
    如果格式化后**不同步回本地**，本地仍是未格式化版本；
    下一次 `upload.py` 又把未格式化版本覆盖回服务器，
    表现为**同一个 lint 错误反复出现**，看起来像"修了没用"。

    更隐蔽的是"只格式化了一部分目录"（例如漏掉 tests），
    下一个人的 selfcheck 就会莫名失败。

    本脚本把「上传 → 全量格式化 → 门禁 → 回传」固化成一个本地命令。

注意：必须在**本地**运行 —— `upload.py` / `sync_from_host.py` 都依赖 paramiko，
目标 上并没有装（它们是"从开发机连服务器"的工具，不是服务器侧脚本）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCOPE = "app tests deploy probes tools"


def _remote_cmd() -> str:
    """构造远端命令。部署根目录从连接配置读取，不写死在脚本里。"""
    sys.path.insert(0, str(HERE))
    from conn import Connection

    return (
        f"cd {Connection.load().root} && "
        f"./venv/bin/ruff check --fix {SCOPE} >/dev/null 2>&1; "
        f"./venv/bin/ruff format {SCOPE} >/dev/null 2>&1; "
        "bash selfcheck.sh"
    )


def run(args: list[str], title: str) -> int:
    print(f"\n=== {title} ===", flush=True)
    proc = subprocess.run([sys.executable, *args], cwd=str(ROOT))
    return proc.returncode


def main() -> int:
    check_only = "--check" in sys.argv

    if run([str(HERE / "upload.py")], "1/3 上传到目标服务器") != 0:
        print("\nPREFLIGHT_FAILED: 上传失败")
        return 1

    if run([str(HERE / "remote.py"), _remote_cmd()], "2/3 远端格式化 + 门禁") != 0:
        print(
            "\nPREFLIGHT_FAILED: 门禁未通过。"
            "注意：此时远端已被格式化，请先 `python deploy/sync_from_host.py` 取回，"
            "再修问题（否则本地与远端会分叉）。"
        )
        return 1

    if check_only:
        print("\nPREFLIGHT_OK（--check：未回传）")
        return 0

    if run([str(HERE / "sync_from_host.py")], "3/3 同步回本地") != 0:
        print("\nPREFLIGHT_FAILED: 回传失败（本地与远端可能已分叉）")
        return 1

    print("\nPREFLIGHT_OK: 上传 + 格式化 + 门禁 + 回传完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
