"""外部命令执行器（适配器层）。

方案约束（V4.1 12.7 第 2~5 条）：
  * 一律使用 ``asyncio.create_subprocess_exec``，从不使用 shell；
  * 必须 ``await proc.communicate()``，避免管道缓冲写满导致死锁；
  * 超时后 terminate → 宽限 → kill → ``await proc.wait()`` 回收；
  * ``CancelledError`` 清理完成后必须重新抛出。

该模块被测试整体替换（不依赖真实 nvidia-smi / systemctl）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from ..config import Settings


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    error: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


class CommandRunner:
    """把外部命令跑成协程，带超时、优雅终止与耗时统计。"""

    def __init__(self, settings: Settings):
        self.s = settings
        self.durations: dict[str, float] = {}
        self.errors: dict[str, int] = {}

    async def run(
        self,
        argv: list[str],
        timeout_s: float | None = None,
        label: str | None = None,
        optional: bool = False,
    ) -> CommandResult:
        """执行外部命令。

        ``optional=True`` 用于**可选探测**（例如 AMD 机器上探测 nvidia-smi、
        没有容器工具链时探测 nvidia-container-cli）：这类命令"不存在"是正常
        结果，不应计入 ``command_errors``（否则运维会把噪声当成故障）。
        判定结果仍会体现在业务字段的 ``missing`` / ``unknown`` 上。
        """
        if not argv:
            raise ValueError("argv must not be empty")
        timeout_s = timeout_s if timeout_s is not None else self.s.cmd_timeout_s
        name = label or argv[0]
        t0 = time.monotonic()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.s.stream_reader_limit,
            )
            async with asyncio.timeout(timeout_s):
                out_b, err_b = await proc.communicate()
            dur = (time.monotonic() - t0) * 1000.0
            self._record(name, dur)
            out = out_b.decode("utf-8", "replace")
            return CommandResult(
                argv=argv,
                returncode=proc.returncode if proc.returncode is not None else -1,
                stdout=out,
                stderr=err_b.decode("utf-8", "replace"),
                duration_ms=dur,
                lines=[ln for ln in out.splitlines() if ln.strip()],
            )
        except TimeoutError:
            await self._terminate(proc)
            dur = (time.monotonic() - t0) * 1000.0
            self._record(name, dur)
            self.errors[name] = self.errors.get(name, 0) + 1
            return CommandResult(
                argv=argv,
                returncode=-1,
                stdout="",
                stderr="",
                duration_ms=dur,
                timed_out=True,
                error=f"timeout after {timeout_s}s",
            )
        except FileNotFoundError as exc:
            dur = (time.monotonic() - t0) * 1000.0
            if not optional:
                self.errors[name] = self.errors.get(name, 0) + 1
            return CommandResult(
                argv=argv, returncode=-1, stdout="", stderr="", duration_ms=dur, error=f"not found: {exc}"
            )
        except asyncio.CancelledError:
            # 清理后必须重抛，否则取消语义被吞掉（12.7 第 5 条）
            await self._terminate(proc)
            raise
        except Exception as exc:  # noqa: BLE001 - 适配器层兜底，不允许冒泡
            await self._terminate(proc)
            dur = (time.monotonic() - t0) * 1000.0
            self.errors[name] = self.errors.get(name, 0) + 1
            return CommandResult(
                argv=argv,
                returncode=-1,
                stdout="",
                stderr="",
                duration_ms=dur,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _terminate(self, proc: asyncio.subprocess.Process | None) -> None:
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            async with asyncio.timeout(self.s.cmd_kill_grace_s):
                await proc.wait()
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    def _record(self, name: str, dur_ms: float) -> None:
        prev = self.durations.get(name)
        self.durations[name] = dur_ms if prev is None else (prev * 0.7 + dur_ms * 0.3)

    def slow_commands(self, threshold_ms: float | None = None) -> dict[str, float]:
        th = threshold_ms if threshold_ms is not None else self.s.cmd_slow_ms
        return {k: round(v, 1) for k, v in self.durations.items() if v > th}
