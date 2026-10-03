#!/usr/bin/env python
"""WebSocket 快照字段完整性验收（v0.5）。

    cd "$WKL_ROOT" && ./venv/bin/python probes/e2e_ws_snapshot.py

**为什么需要这个探针**

    「顶栏框架徽标一直显示识别中」这个缺陷，用 REST 探针**查不出来** ——
    `/api/overview` 的 `framework` 字段是对的。问题在于页面每 2 秒被
    **WebSocket** 推送的 snapshot 覆盖一次，而 snapshot 里没有这个字段。

    因此必须**直接连 WebSocket** 断言字段存在。这正是本次缺陷的回归防线。

实现：手写最小 WebSocket 客户端（raw socket + RFC6455 握手），
不引入 websockets 依赖。
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import socket
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HOST = "127.0.0.1"
PORT = 8081

#: 前端渲染要读、因此必须由 WS 快照提供的字段
REQUIRED_FIELDS = (
    "ts",
    "model",
    "kpi",
    "kv",
    "gpus",
    "system",
    "runtime",
    "thresholds",
    "baseline",
    "accelerator_badge",
    "llama_uptime_s",
    "hardware_ts",
    "framework",  # ← v0.5：缺它就会让徽标退回「识别中…」
)

fails: list[str] = []
passes: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (passes if cond else fails).append(f"{name}{(' — ' + detail) if detail else ''}")


class WS:
    """最小 WebSocket 客户端（只处理文本帧、无掩码要求）。"""

    def __init__(self, host: str, port: int, path: str, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self.buf = b""
        # 读完握手响应头
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("握手期间连接被关闭")
            self.buf += chunk
        head, _, rest = self.buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"握手失败：{head.split(chr(13).encode())[0]!r}")
        self.buf = rest

    def _fill(self, n: int) -> None:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("连接已关闭")
            self.buf += chunk

    def recv_text(self, timeout: float = 10.0) -> str | None:
        """读取下一帧文本；控制帧自动跳过。超时返回 None。"""
        self.sock.settimeout(timeout)
        while True:
            self._fill(2)
            b0, b1 = self.buf[0], self.buf[1]
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            ln = b1 & 0x7F
            off = 2
            if ln == 126:
                self._fill(4)
                ln = int.from_bytes(self.buf[2:4], "big")
                off = 4
            elif ln == 127:
                self._fill(10)
                ln = int.from_bytes(self.buf[2:10], "big")
                off = 10
            if masked:
                self._fill(off + 4)
                mask = self.buf[off : off + 4]
                off += 4
            else:
                mask = None
            self._fill(off + ln)
            payload = self.buf[off : off + ln]
            self.buf = self.buf[off + ln :]
            if mask:
                payload = bytes(p ^ mask[i % 4] for i, p in enumerate(payload))
            if opcode == 0x8:  # close
                return None
            if opcode in (0x9, 0xA):  # ping/pong
                continue
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", "replace")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


def main() -> int:
    print("=== REST 基线 ===")
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/overview", timeout=20) as r:
        rest = json.load(r)
    rest_fw = rest.get("framework") or {}
    print(f"  REST framework.id = {rest_fw.get('id')} version={rest_fw.get('version')}")
    check("REST 下发 framework", bool(rest_fw.get("id")))

    print("\n=== WebSocket /ws/metrics 首帧快照 ===")
    ws = None
    snap = None
    try:
        ws = WS(HOST, PORT, "/ws/metrics", timeout=15.0)
        deadline = time.time() + 25.0
        while time.time() < deadline:
            raw = ws.recv_text(timeout=10.0)
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "snapshot":
                snap = msg.get("payload") or {}
                break
    except Exception as exc:  # noqa: BLE001
        check("WebSocket 能连上并收到快照", False, f"{type(exc).__name__}: {exc}")
    finally:
        if ws:
            ws.close()

    if snap is None:
        check("WebSocket 能连上并收到快照", False, "25 秒内未收到 snapshot 帧")
    else:
        check("WebSocket 能连上并收到快照", True)
        keys = sorted(snap.keys())
        print(f"  快照字段（{len(keys)} 个）：{keys}")

        print("\n=== 必备字段 ===")
        for f in REQUIRED_FIELDS:
            present = f in snap
            check(f"快照含 {f}", present)

        print("\n=== 关键：framework 字段（本缺陷的回归点）===")
        fw = snap.get("framework")
        check("快照含 framework 字段", fw is not None, "缺失 —— 页面每 2 秒被覆盖后徽标会退回「识别中…」")
        if isinstance(fw, dict) and fw:
            print(f"  snapshot.framework.id      = {fw.get('id')}")
            print(f"  snapshot.framework.version = {fw.get('version')}")
            print(f"  snapshot.framework.name    = {(fw.get('name') or {}).get('zh')}")
            check("快照 framework 非空", bool(fw.get("id")))
            check("快照 framework 含 id", bool(fw.get("id")))
            check(
                "快照 framework 含中英双语名称",
                bool((fw.get("name") or {}).get("zh")) and bool((fw.get("name") or {}).get("en")),
            )
            check("快照 framework 含能力清单", bool(fw.get("capabilities")))
            check("快照 framework 含版本号", bool(fw.get("version")))
            # 与 REST 必须一致（同一数据源）
            check(
                "WS 与 REST 的 framework 一致",
                fw.get("id") == rest_fw.get("id") and fw.get("version") == rest_fw.get("version"),
                f"ws={fw.get('id')}/{fw.get('version')} rest={rest_fw.get('id')}/{rest_fw.get('version')}",
            )

    print()
    for p in passes:
        print(f"  [PASS] {p}")
    if fails:
        print()
        print(f"E2E_WS_SNAPSHOT_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print(f"\nE2E_WS_SNAPSHOT_OK: 全部通过（{len(passes)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
