"""GET /api/hardware —— 硬件与运行环境全量识别结果（v0.4 §8.1）。

数据由 ``HardwareCollector`` 提供：全部为**运行时探测**（原则 P1/P2），
按 ``hardware_ttl_s`` 刷新并落盘缓存。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ._deps import ctx

router = APIRouter()


@router.get("/api/hardware")
async def hardware(request: Request) -> dict:
    c = ctx(request)
    force = request.query_params.get("refresh") in ("1", "true", "yes")
    if force and getattr(c, "hardware", None) is not None:
        await c.hardware.collect(force=True)
    info = c.hardware_snapshot() if hasattr(c, "hardware_snapshot") else c.hardware.snapshot()
    body = info.model_dump()
    # 前端条件渲染的唯一依据（R4）：只列出**确实存在**的厂家
    body["vendors"] = list(info.vendors)
    return body
