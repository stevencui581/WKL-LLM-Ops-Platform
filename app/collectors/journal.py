"""journald 日志跟随器（方案 TASK-08 / 12.7 第 8~9、11 条）。

职责：
  * 以子进程方式长期持有 ``journalctl -u <unit> -f -o short-iso``；
  * 用 ``--cursor-file`` 精确续读，重启后不重复也不丢行；
  * 放宽 StreamReader 行上限（默认 64 KiB，journal 长行会抛 LimitOverrunError）；
  * 读循环只做「读一行 → 解析 → 投递」，重活交下游，避免反向阻塞 journalctl；
  * 子进程退出后指数退避重连，重连时回填最近 N 行；
  * 维护一个有界环形缓冲，供 HTTP 查询与 WebSocket 回填。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import deque

from ..config import Settings
from ..models import LogLine
from ..services.log_stats import LogStats
from .logregex import parse_journal_line

log = logging.getLogger("llmconsole.journal")


class JournalFollower:
    def __init__(self, settings: Settings):
        self.s = settings
        self.ring: deque[LogLine] = deque(maxlen=self.s.log_ring_max)
        self.stats = LogStats()
        self._subscribers: set[asyncio.Queue[LogLine]] = set()
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stop = asyncio.Event()
        self.lines_total = 0
        self.parse_failures = 0
        self.restarts = 0
        self.last_line_ts: float = 0.0
        self.running = False
        #: 无法跟随时给用户的**可操作**原因（单元不存在/反复退出），供 health 展示
        self.unavailable_reason: str | None = None
        #: journalctl 退出时的第一行 stderr（诊断用）
        self.last_error: str | None = None
        self._quick_exits = 0

    # ------------------------------------------------------------------
    def build_argv(self) -> list[str]:
        """跟随命令：**只**用 ``--cursor-file``，绝不混入 ``-n`` / ``--since``。

        实测缺陷（v0.6.1）：journalctl 明确禁止
        ``--since`` / ``--cursor`` / ``--cursor-file`` / ``--after-cursor`` 混用，
        混用会直接打印
        "Please specify only one of --since=, --cursor=, --cursor-file=, ..."
        并以 rc=1 退出 —— 而旧代码在**游标文件不存在**时正好把 ``-n`` 和
        ``--since`` 一起传了进去，于是任何全新部署上跟随器都永远起不来。

        首批历史行由 :meth:`backfill` 用一条**独立**查询种子（不带游标），
        因此这里只负责从游标续读。
        """
        return [
            self.s.journalctl,
            "-u",
            self.s.llama_unit,
            "-f",
            "-o",
            "short-iso",
            "--no-pager",
            "--cursor-file",
            self.s.journal_cursor_path,
        ]

    # ------------------------------------------------------------------
    def subscribe(self, maxsize: int | None = None) -> asyncio.Queue[LogLine]:
        q: asyncio.Queue[LogLine] = asyncio.Queue(maxsize=maxsize or self.s.ws_queue_max)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[LogLine]) -> None:
        self._subscribers.discard(q)

    def _publish(self, line: LogLine) -> None:
        """投递给订阅者；满了丢最旧，绝不阻塞读循环。"""
        for q in list(self._subscribers):
            while True:
                try:
                    q.put_nowait(line)
                    break
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        q.get_nowait()

    def recent(self, n: int) -> list[LogLine]:
        return list(self.ring)[-n:]

    # ------------------------------------------------------------------
    async def backfill(self, lines: int | None = None) -> int:
        """一次性读取最近 N 行做种子，保证空闲服务器上日志面板也有内容。

        实测踩坑：只靠 ``-f --cursor-file`` 时，llama-server 空闲十几分钟
        不产生日志，面板会一直空着。这里用一次**不带游标**的查询补种子，
        与跟随循环互不干扰（游标仍由 -f 那条命令维护，不会重复消费）。
        """
        n = lines or self.s.journal_backfill_lines
        argv = [
            self.s.journalctl,
            "-u",
            self.s.llama_unit,
            "-n",
            str(n),
            "--no-pager",
            "-o",
            "short-iso",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.s.stream_reader_limit,
            )
            out_b, _ = await proc.communicate()
        except (FileNotFoundError, OSError) as exc:
            log.warning("journal backfill unavailable: %s", exc)
            return 0
        count = 0
        for raw in out_b.decode("utf-8", "replace").splitlines():
            if not raw.strip():
                continue
            line = parse_journal_line(raw)
            self.ring.append(line)
            self.stats.update(line.text, line.epoch or None)
            self.lines_total += 1
            count += 1
        log.info("journal backfill seeded %d lines", count)
        return count

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        await self.backfill()
        self._task = asyncio.create_task(self._run(), name="journal-follower")

    async def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.running = False

    # ------------------------------------------------------------------
    async def unit_load_state(self) -> str:
        """查询被监控单元的 ``LoadState``（loaded / not-found / masked …）。

        为什么需要它：``journalctl -u <不存在的单元> -f`` **不会报错**，
        它立刻以 rc=0 退出。若不先判断，跟随循环会 1 秒重启一次
        （实测 12 分钟重启 797 次），既刷日志又给不出有用信息。
        """
        argv = [self.s.systemctl, "show", "-p", "LoadState", "--value", self.s.llama_unit]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out_b, _ = await proc.communicate()
        except (FileNotFoundError, OSError) as exc:
            log.debug("systemctl unavailable: %s", exc)
            return "unknown"
        return out_b.decode("utf-8", "replace").strip() or "unknown"

    # ------------------------------------------------------------------
    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            state = await self.unit_load_state()
            if state == "not-found":
                self.running = False
                self.unavailable_reason = (
                    f"systemd 单元 {self.s.llama_unit} 不存在"
                    "（请检查 LLMCONSOLE_LLAMA_UNIT 是否写成了实际单元名）"
                )
                # 单元可能稍后才创建：低频重查，不做快速重启
                await asyncio.sleep(30.0)
                continue
            produced = 0
            try:
                produced = await self._follow_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 跟随循环必须自愈
                log.warning("journal follower error: %s: %s", type(exc).__name__, exc)
                self.unavailable_reason = f"journalctl 启动失败：{type(exc).__name__}: {exc}"
            self.running = False
            if self._stop.is_set():
                break
            self.restarts += 1
            if produced > 0:
                self._quick_exits = 0
                backoff = 1.0
                self.unavailable_reason = None
                self.last_error = None
                await asyncio.sleep(1.0)
                continue
            # 立刻退出且一行都没产出：多半是单元名错/无 journal 权限/参数冲突。
            # 指数退避，避免 1 秒一次的重启风暴。
            self._quick_exits += 1
            if self._quick_exits >= 3:
                detail = f"：{self.last_error}" if self.last_error else ""
                self.unavailable_reason = (
                    f"journalctl 对单元 {self.s.llama_unit} 反复退出且无输出{detail}"
                    "（检查单元名与 journald 读取权限）"
                )
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)

    async def _follow_once(self) -> int:
        os.makedirs(self.s.state_dir, exist_ok=True)
        argv = self.build_argv()
        log.info("starting journal follower: %s", " ".join(argv))
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self.s.stream_reader_limit,
        )
        self.running = True
        produced = 0
        assert self._proc.stdout is not None
        try:
            while not self._stop.is_set():
                raw_b = await self._proc.stdout.readline()
                if not raw_b:
                    break
                raw = raw_b.decode("utf-8", "replace")
                try:
                    line = parse_journal_line(raw)
                except Exception:  # noqa: BLE001 - 解析失败也不能中断采集
                    self.parse_failures += 1
                    line = LogLine(text=raw.rstrip("\n"), ts="", level="I")
                self.lines_total += 1
                produced += 1
                self.last_line_ts = time.time()
                self.ring.append(line)
                self.stats.update(line.text, line.epoch or None)
                self._publish(line)
        finally:
            if self._proc is not None:
                proc = self._proc
                # journalctl 退出前会把错误写到 stderr：先取回来再善后，
                # 否则只看到 rc=1，用户无从下手。
                if proc.returncode is not None and proc.stderr is not None:
                    with contextlib.suppress(Exception):
                        err_b = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                        text = err_b.decode("utf-8", "replace").strip()
                        if text:
                            self.last_error = text.splitlines()[0][:200]
                else:
                    with contextlib.suppress(Exception):
                        proc.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=3)
                rc = proc.returncode
                log.info(
                    "journal follower exited rc=%s%s",
                    rc,
                    f" ({self.last_error})" if self.last_error else "",
                )
                self._proc = None
        return produced
