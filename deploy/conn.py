"""部署连接参数（**不把任何真实主机/凭据写进仓库**）。

    from deploy.conn import Connection
    c = Connection.load()
    c.host, c.port, c.user, c.password, c.root

参数优先级（从高到低）：

  1. **环境变量** —— ``WKL_HOST`` / ``WKL_PORT`` / ``WKL_USER`` /
     ``WKL_PASSWORD`` / ``WKL_ROOT`` / ``WKL_SUDO_PASSWORD``
  2. **本地配置文件** ``deploy/host.env``（**已加入 .gitignore，不会上传**）
  3. 通用占位默认值

为什么这样设计
    v0.5 起本项目开源，仓库里**不能出现任何真实服务器信息**。
    但开发者本人仍要能部署 —— 于是把「连接什么机器」这件事从代码里
    移到「运行环境」：代码保持通用，真实值放在本地未跟踪文件或环境变量里。

``deploy/host.env`` 示例（照抄 ``deploy/host.env.example`` 再填自己的值）::

    WKL_HOST=192.0.2.10
    WKL_PORT=22
    WKL_USER=llmops
    WKL_PASSWORD=your-password
    WKL_ROOT=/opt/WKL-LLM-Ops-Platform
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "host.env"

#: 通用占位默认值 —— 只用于「没配置时给出清晰报错」，不是任何真实机器
DEFAULTS = {
    "WKL_HOST": "192.0.2.10",
    "WKL_PORT": "22",
    "WKL_USER": "llmops",
    "WKL_PASSWORD": "",
    "WKL_ROOT": "/opt/WKL-LLM-Ops-Platform",
    "WKL_SUDO_PASSWORD": "",
}


def _read_env_file() -> dict[str, str]:
    """读取本地 ``deploy/host.env``（KEY=VALUE，支持 # 注释）。"""
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    user: str
    password: str
    root: str
    sudo_password: str = ""

    @classmethod
    def load(cls) -> Connection:
        file_vals = _read_env_file()

        def get(key: str) -> str:
            return os.environ.get(key) or file_vals.get(key) or DEFAULTS.get(key, "")

        return cls(
            host=get("WKL_HOST"),
            port=int(get("WKL_PORT") or 22),
            user=get("WKL_USER"),
            password=get("WKL_PASSWORD"),
            root=get("WKL_ROOT"),
            sudo_password=get("WKL_SUDO_PASSWORD"),
        )

    @property
    def configured(self) -> bool:
        """是否确实配置过（而非仍在用占位默认值）。"""
        return bool(self.password) and self.host not in ("", DEFAULTS["WKL_HOST"])

    def hint(self) -> str:
        return (
            "未配置部署连接信息。请任选一种方式：\n"
            "  1) 复制 deploy/host.env.example 为 deploy/host.env 并填写（该文件不会提交）\n"
            "  2) 设置环境变量 WKL_HOST / WKL_USER / WKL_PASSWORD（可选 WKL_PORT / WKL_ROOT）"
        )
