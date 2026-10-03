"""把工程上传到目标服务器（开发/部署用）。

连接参数来自环境变量或本地 deploy/host.env（见 deploy/conn.py），
仓库里不含任何真实主机与凭据。

用法：
    python deploy/upload.py                 # 上传代码
    python deploy/upload.py --run "pytest"  # 上传后执行远程命令
"""

from __future__ import annotations

import argparse
import glob
import os
import posixpath
import stat
import sys

import paramiko
from conn import Connection

CONN = Connection.load()
REMOTE_ROOT = CONN.root
LOCAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: docs 一并上传：单元文件的 Documentation 与运维手册都依赖它
#: tools 也上传：文档生成器（md2docx）等工具需要在服务器上可被测试覆盖，
#: 否则「文档生成器给中文插零宽空格」这类缺陷在服务器侧无法守卫（v0.4.4）
INCLUDE_DIRS = ("app", "static", "tests", "deploy", "docs", "probes", "tools")

#: 仓库根的固定文件（非 Markdown）
ROOT_FIXED_FILES = (
    "pyproject.toml",
    "conftest.py",
    "selfcheck.sh",
    "LICENSE",
    "CITATION.cff",
    "VERSION",
    ".python-version",
    ".gitignore",  # 开源合规守卫需要检查它
    ".gitattributes",  # 行尾守卫需要检查它
    ".editorconfig",
    ".env.example",
    # 一键安装/升级/卸载脚本 —— 需要在服务器上做 bash -n 语法检查
    "install.sh",
    "update.sh",
    "uninstall.sh",
)

#: 仓库根的 Markdown **全部上传**。
#:
#: 早期版本把根文档逐个列进 INCLUDE_FILES，结果 v0.5.1 新增双语文档时漏传，
#: 服务器上的守卫测试全部误报"文件不存在" —— 与 D9（sync 漏目录）同一类问题。
#: 改为通配，新增文档不必再改这里。
ROOT_MD_GLOBS = ("*.md",)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "build", ".git"}


def _root_files() -> list[str]:
    """收集仓库根需要上传的文件（固定清单 + 全部 Markdown）。"""
    out: list[str] = [f for f in ROOT_FIXED_FILES if os.path.isfile(os.path.join(LOCAL_ROOT, f))]
    seen = set(out)
    for pattern in ROOT_MD_GLOBS:
        for full in sorted(glob.glob(os.path.join(LOCAL_ROOT, pattern))):
            name = os.path.basename(full)
            if name not in seen:
                out.append(name)
                seen.add(name)
    return out


INCLUDE_FILES = _root_files()


def iter_local():
    for d in INCLUDE_DIRS:
        base = os.path.join(LOCAL_ROOT, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_PARTS]
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                # Word/Excel 打开文档时会生成 ~$xxx 锁文件；上传它们既无意义，
                # 而且用户关闭文档时文件会消失，导致读取报 FileNotFoundError
                if f.startswith("~$"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, LOCAL_ROOT).replace("\\", "/")
                yield full, rel
    for f in INCLUDE_FILES:
        full = os.path.join(LOCAL_ROOT, f)
        if os.path.isfile(full):
            yield full, f


def _remote_files(sftp, root: str, dirs: tuple[str, ...]) -> list[str]:
    """列出远程那些「随部署上传」目录下的全部文件（相对 root 的路径）。"""
    out: list[str] = []

    def walk(path: str, rel: str) -> None:
        try:
            entries = sftp.listdir_attr(path)
        except OSError:
            return
        for e in entries:
            child_rel = f"{rel}/{e.filename}" if rel else e.filename
            if stat.S_ISDIR(e.st_mode or 0):
                if e.filename in SKIP_PARTS:
                    continue
                walk(f"{path}/{e.filename}", child_rel)
            else:
                out.append(child_rel)

    for d in dirs:
        walk(f"{root}/{d}", d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="上传后执行的远程命令")
    ap.add_argument("--target", default=REMOTE_ROOT)
    ap.add_argument(
        "--prune",
        action="store_true",
        help="镜像模式：删除远程存在但本地已删除的文件（仅限 INCLUDE_DIRS 内）",
    )
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

    def mkdirs(path: str) -> None:
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except OSError:
                sftp.mkdir(cur)

    mkdirs(args.target)
    local_pairs = sorted(iter_local())
    local_rels = {rel for _, rel in local_pairs}

    count = 0
    for local, rel in local_pairs:
        remote = posixpath.join(args.target, rel)
        mkdirs(posixpath.dirname(remote))
        sftp.put(local, remote)
        count += 1
    sftp.close()
    print(f"uploaded {count} files -> {args.target}")

    if args.prune:
        # 只增不删会导致「本地已清理、服务器还留着」—— 开源合规检查会因此误报
        # （实测：本地扫描 0 命中，服务器上却还有已删除的旧文件）。
        sftp = cli.open_sftp()
        removed = 0
        for rel in _remote_files(sftp, args.target, INCLUDE_DIRS):
            if rel in local_rels:
                continue
            if rel.startswith("deploy/host.env"):
                continue  # 本地凭据文件不参与镜像
            try:
                sftp.remove(posixpath.join(args.target, rel))
                removed += 1
            except OSError:
                pass
        sftp.close()
        print(f"pruned {removed} stale files")

    if args.run:
        cmd = f"cd {args.target} && {args.run}"
        _, so, se = cli.exec_command(cmd, timeout=1800)
        out = so.read().decode("utf-8", "replace")
        err = se.read().decode("utf-8", "replace")
        rc = so.channel.recv_exit_status()
        print(out)
        if err.strip():
            print("[stderr]", err[-4000:])
        cli.close()
        return rc
    cli.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
