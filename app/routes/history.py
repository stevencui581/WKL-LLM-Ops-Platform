"""历史与记录类接口（v0.4.3 TASK-53）。

  * ``GET /api/alert-log``            —— 告警日志（最近 N 条，含产生/恢复）
  * ``GET /api/alert-catalog``        —— 告警代码 → 服务类型/名称（中英双语）
  * ``GET /api/logs/history``         —— 历史服务日志（1/7/30 天）
  * ``GET /api/logs/history/download``—— 导出所选范围为 .log

设计：与既有一致地使用 ``envelope()`` 包装；旧中文字段保留（向后兼容），
同时提供结构化字段供前端按当前语言渲染。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ..services import alert_catalog
from ._deps import ctx, envelope

router = APIRouter()


@router.get("/api/alert-catalog")
async def alert_catalog_route(request: Request) -> dict:
    """告警代码 → 服务类型/名称（中英双语）。

    前端每页加载一次并缓存 —— 告警名称只有一个事实源（后端），
    前端只负责按当前语言挑一种展示。
    """
    c = ctx(request)
    payload = alert_catalog.catalog_payload()
    payload["alert_log"] = c.alert_log.stats() if c.alert_log else {}
    return envelope(c.aggregator.snapshot, payload, "alert-catalog")


@router.get("/api/alert-log")
async def alert_log_route(
    request: Request,
    limit: int = Query(500, ge=1, le=5000, description="返回条数，默认 500"),
    level: str | None = Query(None, description="info/warning/critical，返回该级别及以上"),
    event: str | None = Query(None, description="raised=仅产生，resolved=仅恢复"),
    q: str | None = Query(None, description="关键字过滤"),
) -> dict:
    """告警日志（最新在前）。"""
    c = ctx(request)
    if c.alert_log is None:  # pragma: no cover - 容器始终会注入
        return envelope(
            c.aggregator.snapshot,
            {"entries": [], "returned": 0, "total": 0, "limit": limit, "available": False},
            "alert-log",
        )
    ev = event if event in ("raised", "resolved") else None
    rows = c.alert_log.recent(limit=limit, level=level, q=q, event=ev)
    return envelope(
        c.aggregator.snapshot,
        {
            "entries": [e.as_public() for e in rows],
            "returned": len(rows),
            "total": c.alert_log.total,
            "limit": limit,
            "stats": c.alert_log.stats(),
            "available": True,
        },
        "alert-log",
    )


@router.get("/api/logs/history")
async def logs_history(
    request: Request,
    days: int | None = Query(None, description="1 / 7 / 30；非法值回退默认档"),
    limit: int | None = Query(None, ge=1, le=15000, description="省略则用配置默认值"),
    level: str | None = Query(None, description="I/W/E/D，返回该级别及以上"),
    q: str | None = Query(None, description="关键字过滤"),
    refresh: int = Query(0, ge=0, le=1, description="1 = 跳过缓存"),
) -> dict:
    """历史服务日志（默认最近 30 天）。

    ``limit`` 省略时取配置里的 ``log_history_default_limit`` —— 该值**必须**
    覆盖最大范围的行数，否则 journalctl 的 ``-n`` 会从最旧一侧截断，
    出现"选 30 天却只覆盖 1 天"的假象。
    """
    c = ctx(request)
    res = await c.log_history.fetch(days=days, limit=limit, force=bool(refresh))

    order = {"D": 0, "I": 1, "W": 2, "E": 3}
    lines = res.lines
    if level:
        want = order.get(level.upper(), 1)
        lines = [ln for ln in lines if order.get(ln.level, 1) >= want]
    if q:
        needle = q.lower()
        lines = [ln for ln in lines if needle in ln.text.lower()]

    def dump(ln) -> dict:
        """序列化并补一个本地时区的日期时间（页面直接展示，无需二次格式化）。

        ``LogLine.ts`` 是带时区的 ISO（``2026-10-02T21:18:36+06:00``），
        对表格展示偏长；``ts_local`` 统一成 ``YYYY-MM-DD HH:MM:SS``。
        """
        d = ln.model_dump()
        if ln.epoch:
            d["ts_local"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ln.epoch))
        else:
            d["ts_local"] = (ln.ts or "")[:19].replace("T", " ")
        return d

    return envelope(
        c.aggregator.snapshot,
        {
            "lines": [dump(ln) for ln in lines],
            "returned": len(lines),
            "requested_days": res.requested_days,
            "days_options": list(c.settings.log_history_days_options),
            "covered_from": res.covered_from,
            "covered_to": res.covered_to,
            "covered_days": res.covered_days,
            "total_in_range": res.total_in_range,
            "truncated": res.truncated,
            "available": res.available,
            "error": res.error,
            "elapsed_ms": round(res.elapsed_ms, 1),
            "live_enabled": bool(c.settings.log_history_live_enabled),
            "live_max_lines": int(c.settings.log_history_live_max_lines),
            "source": res.source,
        },
        "logs-history",
    )


@router.get("/api/logs/history/download")
async def logs_history_download(
    request: Request,
    days: int | None = Query(None, description="1 / 7 / 30"),
) -> Response:
    """把所选范围导出为 .log 附件（UTF-8 带 BOM，便于 Windows 记事本识别中文）。"""
    c = ctx(request)
    fname, body, n, err = await c.log_history.export_text(days=days)
    if err:
        return Response(
            content=err,
            media_type="text/plain; charset=utf-8",
            status_code=503,
            headers={"X-Export-Error": err[:200]},
        )
    data = ("\ufeff" + body).encode("utf-8")
    return Response(
        content=data,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Export-Lines": str(n),
            "Cache-Control": "no-store",
        },
    )
