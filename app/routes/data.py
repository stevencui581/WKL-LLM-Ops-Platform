"""GPU / 槽位 / LLM / 系统 / 配置 / 历史 / 日志 查询端点（方案 7.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ._deps import ctx, envelope

router = APIRouter()


@router.get("/api/gpu")
async def gpu(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(
        snap,
        {
            "gpus": [g.model_dump() for g in snap.gpus],
            "vram_used_mib": snap.kpi.vram_used_mib,
            "vram_total_mib": snap.kpi.vram_total_mib,
        },
        "gpu",
    )


@router.get("/api/slots")
async def slots(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(snap, snap.kv.model_dump(), "slots")


@router.get("/api/llm")
async def llm(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(
        snap,
        {
            "kpi": snap.kpi.model_dump(),
            "kv": {
                "pct": snap.kv.pct,
                "used_tokens": snap.kv.used_tokens,
                "total_tokens": snap.kv.total_tokens,
                "remaining_tokens": snap.kv.remaining_tokens,
            },
            "runtime": snap.runtime.model_dump(),
        },
        "slots",
    )


@router.get("/api/system")
async def system(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(snap, {"system": snap.system.model_dump(), "self": snap.self_info.model_dump()}, "sys")


@router.get("/api/config")
async def runtime_config(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(snap, snap.runtime.model_dump(), "config")


@router.get("/api/history")
async def history(request: Request, minutes: float = Query(5.0, gt=0, le=60)) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    return envelope(snap, c.history.window(minutes * 60.0), None)


@router.get("/api/logs")
async def logs(
    request: Request,
    n: int = Query(40, ge=1, le=1000),
    level: str | None = Query(None, description="I/W/E/D，返回该级别及以上"),
    q: str | None = Query(None, description="关键字过滤"),
    slot: int | None = Query(None, ge=0),
) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot

    order = {"D": 0, "I": 1, "W": 2, "E": 3}
    lines = c.journal.ring
    if level:
        want = order.get(level.upper(), 1)
        lines = [ln for ln in lines if order.get(ln.level, 1) >= want]
    if slot is not None:
        lines = [ln for ln in lines if ln.slot == slot]
    if q:
        needle = q.lower()
        lines = [ln for ln in lines if needle in ln.text.lower()]
    picked = list(lines)[-n:]
    return envelope(
        snap, {"lines": [ln.model_dump() for ln in picked], "total_in_ring": len(c.journal.ring)}, "logs"
    )
