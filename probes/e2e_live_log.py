#!/usr/bin/env python
"""实时日志通道端到端验证（v0.4.3 R11「可以显示实时日志变化」）。

    cd /home/llmops/llm-console && ./venv/bin/python probes/e2e_live_log.py

验证历史日志页所依赖的 ``/ws/logs`` 通道确实能推送实时增量：
  1. 连接后首帧必须是 ``backfill``（页面据此判断"这是历史基线，要忽略"）；
  2. 触发一次推理请求 → 必须收到 ``{type:"log"}`` 实时帧；
  3. 断开后控制台的 ``log_clients`` 必须**回落到连接前的基线**（订阅不泄漏）。

  注意：判据是**增量归零**而不是绝对值归零 —— 运维本人可能正开着控制台页面，
  此时基线本来就不是 0（第一版断言 `after == 0` 曾因此误报）。

注意：本脚本用原生 socket 实现最小 WebSocket 客户端，避免引入第三方库。
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import socket
import struct
import sys
import time
import urllib.request

HOST, PORT = "127.0.0.1", 8081
LLAMA = "http://127.0.0.1:8080"
B = f"http://{HOST}:{PORT}"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


class WS:
    """极简 WebSocket 客户端（仅 text 帧，够用即可）。"""

    def __init__(self, path: str, timeout: float = 10.0):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {HOST}:{PORT}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self.buf = b""
        # 读完握手响应头
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("握手失败：连接被关闭")
            self.buf += chunk
        head, _, rest = self.buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError(f"握手失败：{head!r}")
        self.buf = rest

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("连接已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout: float = 6.0):
        """读一个帧，返回 (opcode, payload)。"""
        self.sock.settimeout(timeout)
        b1, b2 = self._read(2)
        opcode = b1 & 0x0F
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(ln) if ln else b""
        if opcode == 0x9:  # ping → 回 pong
            self.send(payload, opcode=0xA)
            return self.recv(timeout)
        return opcode, payload

    def send(self, data: bytes, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        header = bytes([0x80 | opcode])
        n = len(data)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(header + mask + masked)

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


def log_clients() -> int:
    with urllib.request.urlopen(f"{B}/api/health", timeout=10) as r:
        d = json.load(r)
    return int(d.get("counters", {}).get("ws", {}).get("log_clients", d.get("ws", {}).get("log_clients", -1)))


def trigger_generation() -> None:
    payload = json.dumps(
        {"prompt": "写出 200 个字的服务器运维说明。", "n_predict": 120, "stream": False}
    ).encode()
    req = urllib.request.Request(
        f"{LLAMA}/completion", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read(64)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    print("=== 1. 连接 /ws/logs ===")
    before = log_clients()
    print(f"  连接前 log_clients = {before}")
    try:
        ws = WS("/ws/logs")
    except Exception as exc:  # noqa: BLE001
        print(f"  连接失败：{exc}")
        print("\nE2E_LIVE_FAILED")
        return 1
    check("WebSocket 握手成功", True)

    print("\n=== 2. 首帧必须是 backfill（页面据此忽略历史基线）===")
    first = None
    try:
        while True:
            op, payload = ws.recv(timeout=6)
            if op != 0x1:
                continue
            first = json.loads(payload.decode("utf-8"))
            break
    except Exception as exc:  # noqa: BLE001
        print(f"  读取首帧失败：{exc}")
    check("收到首帧", first is not None)
    if first:
        print(f"  首帧 type = {first.get('type')}, 行数 = {len(first.get('payload') or [])}")
        check("首帧为 backfill", first.get("type") == "backfill", str(first.get("type")))

    print("\n=== 3. 触发推理 → 应收到实时 log 帧 ===")
    time.sleep(0.3)
    trigger_generation()
    got: list[dict] = []
    deadline = time.time() + 25
    while time.time() < deadline and len(got) < 3:
        try:
            op, payload = ws.recv(timeout=5)
        except Exception:  # noqa: BLE001
            continue
        if op != 0x1:
            continue
        msg = json.loads(payload.decode("utf-8"))
        if msg.get("type") == "log":
            got.append(msg["payload"])
    print(f"  收到 {len(got)} 条实时日志")
    for line in got[:3]:
        print(f"    [{line.get('level')}] {line.get('ts')} {str(line.get('text'))[:70]}")
    check("收到实时 log 帧", len(got) > 0)
    if got:
        check("实时帧含时间戳", bool(got[0].get("ts")))
        check("实时帧含级别", bool(got[0].get("level")))
        check("实时帧含正文", bool(got[0].get("text")))

    print("\n=== 4. 断开 → 订阅必须释放（不泄漏）===")
    during = log_clients()
    # 判定必须按**增量**：可能已有其它客户端（例如运维本人正开着控制台页面），
    # 此时基线不是 0。第一版断言 `after == 0` 就是这么误报的。
    check("连接后计数 +1", during == before + 1, f"{before} → {during}")
    ws.close()
    time.sleep(2.5)
    after = log_clients()
    print(f"  基线 {before} → 连接中 {during} → 断开后 {after}")
    check("断开后回到基线（本连接已释放）", after == before, f"期望回到 {before}，实际 {after}")
    if before == 0:
        check("无其它客户端时归零", after == 0, str(after))

    print()
    if fails:
        print(f"E2E_LIVE_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print("E2E_LIVE_OK: 实时日志通道通过（backfill → 增量 → 释放）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
