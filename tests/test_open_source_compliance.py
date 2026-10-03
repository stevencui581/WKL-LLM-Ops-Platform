"""开源合规守卫（v0.5 第 2 步）。

本项目要上传到 GitHub 共享，仓库里**不得出现任何真实部署信息**。
本文件把这条要求固化为可重复执行的检查：

  * 无 CRLF 行尾（Windows 上开发最容易踩的坑：shell 脚本会报
    ``pipefail: invalid option name``）
  * ``.gitignore`` 确实忽略了本地凭据文件
  * 部署脚本不含真实主机/用户/密码，连接参数来自环境或本地未跟踪文件
  * 系统服务单元是**模板**（部署时才渲染），不含具体用户名与路径
  * systemd 单元与 systemd 相关的被监控单元名可配置
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ("app", "tests", "tools", "probes", "deploy", "docs", "static")
SKIP_DIRS = {"__pycache__", ".venv", ".git", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

#: **二进制**扩展名黑名单。
#:
#: 早期版本用"文本扩展名白名单"，漏掉了 ``.csv`` 与**无扩展名**的文件。
#: 后者（``deploy/sudoers.llm-console``）带 CRLF 会**直接破坏 sudoers 解析** ——
#: 属于静默的部署故障。因此改为黑名单：默认认为所有文件都是文本。
BINARY_EXTS = {
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".pyc",
    ".pyo",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp3",
    ".mp4",
    ".webm",
}


def _iter_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or any(x in SKIP_DIRS for x in p.parts):
                continue
            # 本地凭据文件不参与（它本来就不该提交）
            if p.name == "host.env":
                continue
            if p.suffix.lower() in BINARY_EXTS:
                continue
            yield p
    for name in (".gitignore", "README.md", "README.en.md", "pyproject.toml", "conftest.py", "selfcheck.sh"):
        p = ROOT / name
        if p.is_file():
            yield p


# ===========================================================================
# 1. 行尾：必须全部 LF
# ===========================================================================
def test_no_crlf_line_endings():
    """**回归**：Windows 上用 Python ``write_text`` 会把 LF 写成 CRLF。

    现象分三种，都很隐蔽：

    * shell 脚本报 ``set: pipefail: invalid option name``（``pipefail\\r`` 被当选项名）
    * **无扩展名的配置文件**（如 sudoers）解析失败，且报错不直观
    * CSV 数据文件的第一列列名多出 ``\\ufeff``

    这是"在 Windows 上做 Linux 项目"最容易踩的坑之一。
    """
    crlf = [str(p.relative_to(ROOT)) for p in _iter_files() if b"\r\n" in p.read_bytes()]
    assert not crlf, "以下文件是 CRLF 行尾，请运行 tools/fix_line_endings.py：\n" + "\n".join(crlf)


def test_sudoers_file_is_lf_only():
    """**回归**：sudoers 文件带 CRLF 会让白名单**静默失效**。

    这个文件没有扩展名，早期的"扩展名白名单"扫描把它漏掉了。
    """
    p = ROOT / "deploy" / "sudoers.llm-console"
    assert p.is_file(), "缺少 deploy/sudoers.llm-console"
    raw = p.read_bytes()
    assert b"\r" not in raw, "sudoers 文件含 CR（CRLF），会导致 sudoers 解析失败"
    assert not raw.startswith(b"\xef\xbb\xbf"), "sudoers 文件不应带 BOM"


def test_fixture_names_have_no_deployment_id():
    """测试夹具的文件名/常量名不得带特定部署编号或主机标识。

    夹具内容可以来自真实采集（用于验证解析器），但**名字**不该暴露部署信息。
    """
    import re as _re

    # 本文件按设计必须写出待查模式（它就是守卫），不能自扫
    self_name = Path(__file__).name
    bad: list[str] = []
    for p in (ROOT / "tests").rglob("*"):
        if p.is_file() and _re.search(r"_?253\b|\btbea", p.name):
            bad.append(str(p.relative_to(ROOT)))
    for p in (ROOT / "tests").rglob("*.py"):
        if p.name == self_name:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = ln.split("#", 1)[0]
            if _re.search(r"\b[A-Z_]+_253\b|sync_from_253", code):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert not bad, "夹具命名含部署标识：\n" + "\n".join(bad)


def test_shell_scripts_have_lf_shebang():
    """shell 脚本首行必须能被内核正确解析（无 BOM、无 CRLF）。"""
    bad: list[str] = []
    for p in list(ROOT.glob("*.sh")) + list((ROOT / "deploy").glob("*.sh")):
        head = p.read_bytes().split(b"\n", 1)[0]
        if not head.startswith(b"#!/usr/bin/env bash"):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, f"以下脚本首行不是标准 bash shebang：{bad}"


# ===========================================================================
# 2. 凭据不进仓库
# ===========================================================================
def test_gitignore_covers_local_credentials():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for must in ("deploy/host.env", "__pycache__/", ".venv/", "state/"):
        assert must in gi, f".gitignore 必须忽略 {must}"


def test_example_env_has_no_real_values():
    """示例配置只能有占位值。"""
    p = ROOT / "deploy" / "host.env.example"
    assert p.exists(), "必须提供 deploy/host.env.example"
    txt = p.read_text(encoding="utf-8")
    assert "change-me" in txt, "示例密码应为占位值"
    for private in ("172.", "192.168", "10.0.", "tbea"):
        assert private not in txt, f"示例文件里不应出现真实网段/主机名：{private}"


def test_deploy_scripts_read_connection_from_env():
    """部署脚本不得内联真实主机与凭据。"""
    for name in ("deploy/remote.py", "deploy/upload.py", "deploy/sync_from_host.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "from conn import Connection" in src, f"{name} 应使用 deploy/conn.py"
        assert not re.search(r"HOST,\s*PORT,\s*USER,\s*PWD\s*=", src), f"{name} 仍内联连接常量"


def test_conn_module_reads_env_or_local_file():
    src = (ROOT / "deploy" / "conn.py").read_text(encoding="utf-8")
    assert "WKL_HOST" in src and "WKL_PASSWORD" in src
    assert "host.env" in src
    assert "environ" in src, "必须支持环境变量覆盖"


# ===========================================================================
# 3. 系统服务单元是模板
# ===========================================================================
@pytest.mark.parametrize("unit", ["deploy/llm-console.service", "deploy/llm-console-observe.service"])
def test_unit_files_are_templates(unit):
    src = (ROOT / unit).read_text(encoding="utf-8")
    assert "__USER__" in src, f"{unit} 应使用 __USER__ 占位"
    assert "__ROOT__" in src, f"{unit} 应使用 __ROOT__ 占位"
    # 不得残留具体用户与主目录
    assert not re.search(r"^User=(?!__)", src, re.M), f"{unit} 的 User= 必须是占位"
    assert "/home/" not in src, f"{unit} 不应含具体主目录"


def test_infer_unit_is_configurable():
    """被监控的推理单元名必须可配置 —— 换框架/换机器不用改代码。"""
    src = (ROOT / "deploy" / "llm-console.service").read_text(encoding="utf-8")
    assert "LLMCONSOLE_LLAMA_UNIT=__INFER_UNIT__" in src
    assert "LLMCONSOLE_LLAMA_BASE_URL" in src
    inst = (ROOT / "deploy" / "install_service.sh").read_text(encoding="utf-8")
    assert "LLM_INFER_UNIT" in inst, "安装脚本应允许覆盖被监控单元名"
    assert "__INFER_UNIT__" in inst, "安装脚本应渲染模板占位"


def _strip_sh_comments(src: str) -> str:
    """去掉 shell 注释，只留可执行行。

    必须剥离：说明「不要这么写」的注释本身就会包含那个反面模式
    （例如 ``# 不能写成 render ... | sudo_do tee ...``），
    不剥离会造成误报 —— 与源码扫描必须先剥注释是同一个教训。
    """
    return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def test_install_scripts_render_but_do_not_pipe_to_sudo():
    """**回归**：不能把渲染内容管道给 ``sudo -S``。

    ``sudo -S`` 从 stdin 读密码，管道内容会被密码提示吃掉，
    结果写出 0 字节文件 —— systemd 会把空单元文件视为 **masked**（实测踩过）。
    """
    for name in ("deploy/install_service.sh", "deploy/install_sudoers.sh"):
        src = _strip_sh_comments((ROOT / name).read_text(encoding="utf-8"))
        assert "| sudo_do tee" not in src, f"{name} 不得把渲染内容管道给 sudo"
        assert "mktemp" in src, f"{name} 应先渲染到临时文件再 install"


def test_no_private_ips_in_repo():
    """全仓不得出现内网私有 IP（含代码、注释、文档）。"""
    pat = re.compile(
        r"\b(?:10|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
        r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
    )
    bad: list[str] = []
    for p in _iter_files():
        try:
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                m = pat.search(ln)
                if m:
                    bad.append(f"{p.relative_to(ROOT)}:{i}: {m.group(0)}")
        except (UnicodeDecodeError, OSError):
            continue
    assert not bad, "仓库里出现内网私有 IP：\n" + "\n".join(bad)


def test_no_home_paths_in_repo():
    """全仓不得出现开发者本机主目录路径。

    ``/home/llmops/`` 是文档里的通用示例（新增用户），允许保留；
    ``/home/.../`` 这类纯省略号也不算（它是占位，不是真实路径）。
    """
    pat = re.compile(r"/(?:home|Users)/(?!llmops\b)[A-Za-z_][A-Za-z0-9._-]*/")
    bad: list[str] = []
    for p in _iter_files():
        try:
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                m = pat.search(ln)
                if m:
                    bad.append(f"{p.relative_to(ROOT)}:{i}: {m.group(0)}")
        except (UnicodeDecodeError, OSError):
            continue
    assert not bad, "仓库里出现本机主目录路径：\n" + "\n".join(bad)
