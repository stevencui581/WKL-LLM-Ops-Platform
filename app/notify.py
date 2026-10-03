"""systemd 集成：就绪通知与看门狗（方案 12.7 第 17 条）。

纯标准库实现，向 ``$NOTIFY_SOCKET`` 发送数据报；``@`` 开头是抽象命名空间，
需要补一个前导 ``\\0``。不依赖 systemd-python C 扩展。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket

log = logging.getLogger("llmconsole.notify")


def notify(state: str) -> bool:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(state.encode("utf-8"))
        return True
    except OSError as exc:
        log.debug("sd_notify failed: %s", exc)
        return False


def ready() -> None:
    notify("READY=1")


def watchdog() -> None:
    notify("WATCHDOG=1")


def reloading() -> None:
    notify("RELOADING=1")


def stopping() -> None:
    notify("STOPPING=1")


def status(text: str) -> None:
    notify(f"STATUS={text}")


class Watchdog:
    """每 WatchdogSec/2 秒发一次 WATCHDOG=1。未配置时为空转。"""

    def __init__(self, interval_s: float = 10.0):
        self.interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(os.environ.get("WATCHDOG_USEC"))

    async def start(self) -> None:
        if not self.enabled:
            return
        usec = int(os.environ.get("WATCHDOG_USEC", "0"))
        self.interval_s = max(1.0, (usec / 1_000_000.0) / 2.0)
        self._task = asyncio.create_task(self._loop(), name="watchdog")

    async def _loop(self) -> None:
        while True:
            watchdog()
            await asyncio.sleep(self.interval_s)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
