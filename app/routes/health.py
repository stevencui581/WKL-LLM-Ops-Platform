"""健康检查（方案 TASK-13 / 12.7 第 15 条）。

``/api/health/live``  —— 不查任何依赖，进程活着就 200；
``/api/health/ready`` —— 只读各数据源缓存时间戳，任一不可用返回 **503**；
``/api/health``       —— 兼容入口，等同 ready 但始终 200 并给出明细。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ._deps import ctx

router = APIRouter()


@router.get("/api/health/live")
async def live() -> dict:
    return {"ok": True, "check": "liveness"}


@router.get("/api/health/ready")
async def ready(request: Request):
    c = ctx(request)
    ok, reasons = c.aggregator.ready()
    body = {
        "ok": ok,
        "check": "readiness",
        "reasons": reasons,
        "checks": c.aggregator.health(),
        "runtime": c.aggregator.snapshot.runtime.model_dump(),
        "self": c.aggregator.snapshot.self_info.model_dump(),
        "ws": c.hub.stats(),
        "counters": {
            "ticks": c.tick_count,
            "snapshots": c.aggregator.seq,
            "journal_lines": c.journal.lines_total,
            "journal_restarts": c.journal.restarts,
            "journal_parse_failures": c.journal.parse_failures,
            "command_errors": c.runner.errors,
            "slow_commands": c.runner.slow_commands(),
        },
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/api/health")
async def health(request: Request) -> dict:
    """诊断入口：始终 200，便于人工排查。"""
    c = ctx(request)
    ok, reasons = c.aggregator.ready()
    return {
        "ok": ok,
        "reasons": reasons,
        "checks": c.aggregator.health(),
        "ws": c.hub.stats(),
        "counters": {
            "ticks": c.tick_count,
            "snapshots": c.aggregator.seq,
            "journal_lines": c.journal.lines_total,
            "journal_restarts": c.journal.restarts,
            "journal_parse_failures": c.journal.parse_failures,
            "command_errors": c.runner.errors,
        },
    }
