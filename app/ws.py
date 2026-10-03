"""WebSocket Hub（方案 TASK-12 / 7.4 / 12.7 第 11~14 条）。

关键约束：
  * 每个连接一条**有界**队列 + 一个独立发送任务；
  * **禁止**在采集循环里直接 ``await ws.send_*`` —— 一个慢客户端会拖死全部；
  * 队满时丢最旧帧并计数，只保证客户端拿到最新一帧；
  * 发送超时即断开该连接；断开后必须在 ``finally`` 中退订。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .config import Settings

log = logging.getLogger("llmconsole.ws")


class _Connection:
    __slots__ = ("ws", "queue", "task", "closed", "dropped", "sent")

    def __init__(self, ws: WebSocket, maxsize: int):
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self.task: asyncio.Task | None = None
        self.closed = False
        self.dropped = 0
        self.sent = 0

    def offer(self, payload: str) -> None:
        if self.closed:
            return
        while True:
            try:
                self.queue.put_nowait(payload)
                return
            except asyncio.QueueFull:
                self.dropped += 1
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()


class WebSocketHub:
    def __init__(self, settings: Settings):
        self.s = settings
        self._metrics: set[_Connection] = set()
        self._logs: set[_Connection] = set()
        self._seq = 0
        self.total_dropped = 0
        self.total_sent = 0
        self.total_connections = 0

    # ------------------------------------------------------------------
    @property
    def client_count(self) -> int:
        return len(self._metrics) + len(self._logs)

    def stats(self) -> dict:
        return {
            "metrics_clients": len(self._metrics),
            "log_clients": len(self._logs),
            "total_connections": self.total_connections,
            "total_sent": self.total_sent,
            "total_dropped": self.total_dropped,
        }

    # ------------------------------------------------------------------
    async def _sender(self, conn: _Connection, channel: str) -> None:
        try:
            while not conn.closed:
                try:
                    payload = await conn.queue.get()
                except asyncio.CancelledError:
                    raise
                async with asyncio.timeout(self.s.ws_send_timeout_s):
                    await conn.ws.send_text(payload)
                conn.sent += 1
                self.total_sent += 1
        except TimeoutError:
            log.info("ws %s client too slow, closing", channel)
            conn.closed = True
            with contextlib.suppress(Exception):
                await conn.ws.close(code=1013)
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            conn.closed = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("ws sender stopped: %s: %s", type(exc).__name__, exc)
            conn.closed = True

    async def _accept(self, ws: WebSocket, bucket: set[_Connection], channel: str) -> _Connection:
        await ws.accept()
        conn = _Connection(ws, self.s.ws_queue_max)
        bucket.add(conn)
        self.total_connections += 1
        conn.task = asyncio.create_task(self._sender(conn, channel), name=f"ws-sender-{channel}")
        return conn

    async def _teardown(self, conn: _Connection, bucket: set[_Connection], channel: str) -> None:
        # 退订必须放在 finally，否则每次刷新页面都会泄漏订阅
        bucket.discard(conn)
        conn.closed = True
        if conn.task is not None:
            conn.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await conn.task
        with contextlib.suppress(Exception):
            await conn.ws.close()
        self.total_dropped += conn.dropped
        log.debug("ws %s client disconnected (sent=%d dropped=%d)", channel, conn.sent, conn.dropped)

    # ------------------------------------------------------------------
    @staticmethod
    def snapshot_payload(snapshot: Any) -> dict:
        """统一的快照 JSON：把 ``self_info`` 改名成 ``self``。

        /api/overview 用的是 ``self``，WebSocket 若原样 model_dump 会得出
        ``self_info``，前端要写两套字段名。这里统一成 ``self``。
        """
        data = snapshot.model_dump()
        if "self_info" in data:
            data["self"] = data.pop("self_info")
        return data

    def broadcast_snapshot(self, snapshot: Any) -> int:
        """由采集循环调用：一次序列化，多次入队。**不 await 发送**。"""
        self._seq += 1
        payload = json.dumps(
            {
                "type": "snapshot",
                "seq": self._seq,
                "ts": snapshot.ts,
                "payload": self.snapshot_payload(snapshot),
            },
            ensure_ascii=False,
            default=str,
        )
        for c in list(self._metrics):
            c.offer(payload)
        return len(self._metrics)

    def broadcast_alert(self, alert: Any, resolved: bool = False) -> None:
        payload = json.dumps(
            {
                "type": "alert",
                "resolved": resolved,
                "payload": alert.model_dump() if hasattr(alert, "model_dump") else alert,
            },
            ensure_ascii=False,
            default=str,
        )
        for c in list(self._metrics):
            c.offer(payload)

    def broadcast_log(self, line: Any) -> None:
        payload = json.dumps(
            {
                "type": "log",
                "seq": self._seq,
                "payload": line.model_dump() if hasattr(line, "model_dump") else line,
            },
            ensure_ascii=False,
            default=str,
        )
        for c in list(self._logs):
            c.offer(payload)

    # ------------------------------------------------------------------
    async def handle_metrics(self, ws: WebSocket, snapshot_provider) -> None:
        conn = await self._accept(ws, self._metrics, "metrics")
        try:
            snap = snapshot_provider()
            if snap is not None:
                conn.offer(
                    json.dumps(
                        {
                            "type": "snapshot",
                            "seq": self._seq,
                            "ts": snap.ts,
                            "payload": self.snapshot_payload(snap),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
            while not conn.closed:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=self.s.ws_ping_interval_s)
                except TimeoutError:
                    conn.offer(json.dumps({"type": "ping", "ts": time.time()}))
                    continue
                if msg == "ping":
                    conn.offer(json.dumps({"type": "pong", "ts": time.time()}))
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.debug("ws metrics receive loop ended: %s", exc)
        finally:
            await self._teardown(conn, self._metrics, "metrics")

    async def _watch_disconnect(self, ws: WebSocket, conn: _Connection) -> None:
        """专职读取客户端帧，以便**立刻**发现断线。

        只靠发送侧发现断线是不够的：客户端断开后若没有数据要发，
        连接会一直挂到下一次发送失败为止（最长一个 ping 周期），
        期间订阅一直占着 —— 实测踩到过这个泄漏。
        """
        try:
            while not conn.closed:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("ws watcher ended: %s", exc)
        finally:
            conn.closed = True

    async def handle_logs(self, ws: WebSocket, follower) -> None:
        conn = await self._accept(ws, self._logs, "logs")
        queue = follower.subscribe()
        watcher = asyncio.create_task(self._watch_disconnect(ws, conn), name="ws-log-watch")
        getter: asyncio.Task | None = None
        try:
            backfill = follower.recent(self.s.journal_backfill_lines)
            conn.offer(
                json.dumps(
                    {
                        "type": "backfill",
                        "payload": [ln.model_dump() for ln in backfill],
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
            getter = asyncio.create_task(queue.get())
            while not conn.closed:
                # 必须和断线监听任务竞速：否则客户端断开后，主循环还卡在
                # queue.get() 上等一个 ping 周期（30 秒），订阅会一直挂着。
                done, _ = await asyncio.wait(
                    {getter, watcher},
                    timeout=self.s.ws_ping_interval_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if watcher in done:
                    break
                if getter in done:
                    line = getter.result()
                    conn.offer(
                        json.dumps(
                            {"type": "log", "payload": line.model_dump()},
                            ensure_ascii=False,
                            default=str,
                        )
                    )
                    getter = asyncio.create_task(queue.get())
                else:
                    conn.offer(json.dumps({"type": "ping", "ts": time.time()}))
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.debug("ws logs loop ended: %s", exc)
        finally:
            if getter is not None:
                getter.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await getter
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await watcher
            follower.unsubscribe(queue)
            await self._teardown(conn, self._logs, "logs")
