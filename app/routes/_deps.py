"""路由层公共依赖与响应信封（方案 7.1）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request


def ctx(request: Request):
    return request.app.state.ctx


def envelope(snap, data: Any, stale_key: str | None = None) -> dict:
    return {
        "ts": time.time(),
        "seq": snap.seq if snap else 0,
        "stale": (snap.stale.get(stale_key, False) if (snap and stale_key) else False),
        "data": data,
    }


def flat(snap, data: dict) -> dict:
    out = {"ts": time.time(), "seq": snap.seq if snap else 0}
    out.update(data)
    return out
