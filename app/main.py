"""WKL-LLM运维平台 v0.1 —— FastAPI 应用入口。

对照 V4.1 方案：
  * 5.3 架构图 / 6.3 后端服务设计 / 7.x API 设计
  * 12.4：**必须单 worker**（多 worker 会各起一个 journalctl、各自持有环形缓冲）
  * lifespan 清理必须 cancel **并** await gather（12.7 第 6 条）
  * 17：Type=notify + WatchdogSec 就绪通知与看门狗
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import notify, routes
from .adapters.exec import CommandRunner
from .adapters.llama import LlamaClient
from .collectors.gpu import GpuCollector
from .collectors.hardware import HardwareCollector
from .collectors.history import LogHistory
from .collectors.journal import JournalFollower
from .collectors.prometheus import PrometheusCollector
from .collectors.props import PropsCollector
from .collectors.slots import SlotsCollector
from .collectors.system import SystemCollector
from .config import Settings, get_settings
from .logging_setup import setup_logging
from .models import HardwareInfo
from .services.aggregator import Aggregator
from .services.alert_log import AlertLog
from .services.alerts import AlertEngine
from .services.baseline import BaselineLearner
from .services.framework import FrameworkInfo
from .services.framework import detect as detect_framework
from .services.history import History
from .services.service_ctl import ServiceController
from .services.unitinfo import UnitConfig, read_unit
from .ws import WebSocketHub

log = logging.getLogger("llmconsole.main")


@dataclass
class Container:
    settings: Settings
    runner: CommandRunner
    client: LlamaClient
    slots: SlotsCollector
    props: PropsCollector
    gpu: GpuCollector
    system: SystemCollector
    metrics: PrometheusCollector
    journal: JournalFollower
    alerts: AlertEngine
    history: History
    aggregator: Aggregator
    hub: WebSocketHub
    service: ServiceController
    #: v0.4 新增
    hardware: HardwareCollector
    baselines: BaselineLearner
    #: v0.4.3 新增
    alert_log: AlertLog
    log_history: LogHistory
    #: v0.5 新增：推理框架识别结果（llama.cpp / ollama / vLLM / SGLang / …）
    framework: FrameworkInfo | None = None
    tick_count: int = 0
    last_tick_ts: float = 0.0
    tasks: list[asyncio.Task] = field(default_factory=list)
    watchdog: notify.Watchdog = field(default_factory=notify.Watchdog)

    #: v0.4 R2：顶栏模型全称所需的完整路径
    def props_model_path(self) -> str:
        p = getattr(self.props, "props", {}) or {}
        return str(p.get("model_path") or p.get("model_alias") or "")

    def hardware_snapshot(self) -> HardwareInfo:
        return self.hardware.snapshot()


def load_unit_config(settings: Settings) -> UnitConfig:
    """读取 llama-server 的真实运行参数（方案 6.4.4 配置徽标的权威来源）。"""
    cfg = read_unit(settings.llama_unit)
    log.info(
        "unit config: spec_type=%s draft_n_max=%s flash_attn=%s tensor_split=%s parallel=%s n_ctx=%s metrics=%s",
        cfg.spec_type or "-",
        cfg.draft_n_max or "-",
        cfg.flash_attn,
        cfg.tensor_split or "-",
        cfg.parallel or "-",
        cfg.n_ctx or "-",
        cfg.metrics_flag,
    )
    return cfg


def build_container(settings: Settings) -> Container:
    runner = CommandRunner(settings)
    client = LlamaClient(settings)
    slots = SlotsCollector(settings, client)
    props = PropsCollector(settings, client)
    gpu = GpuCollector(settings, runner)
    system = SystemCollector(settings)
    metrics = PrometheusCollector(settings, client)
    journal = JournalFollower(settings)
    # v0.4 §7：自动基线学习器（F4）——告警基线不再写死
    baselines = BaselineLearner(settings)
    # v0.4.3 §6.1：告警日志（记录产生/恢复，重启不丢）
    alert_log = AlertLog(
        Path(settings.alert_log_resolved_path),
        ring_max=int(settings.alert_log_ring_max),
        file_max=int(settings.alert_log_file_max),
        service=settings.llama_unit,
    )
    loaded = alert_log.load()
    log.info("alert log ready: %d entries loaded from %s", loaded, alert_log.path)
    alerts = AlertEngine(settings, baselines, alert_log)
    history = History(settings)
    # v0.4.3 §3：历史服务日志（1/7/30 天，按需查询 journald）
    log_history = LogHistory(settings)
    hub = WebSocketHub(settings)
    # v0.4 §5：硬件与软件栈清点（含 DMI / 算力卡厂家 / 依赖组件）
    hardware = HardwareCollector(settings, runner)
    aggregator = Aggregator(
        settings,
        slots=slots,
        props=props,
        gpu=gpu,
        system=system,
        metrics=metrics,
        journal=journal,
        alerts=alerts,
        hardware=hardware,
        baselines=baselines,
    )
    service = ServiceController(settings, runner)
    # v0.4 决策 B1：聚合器需要服务运行时长（限流刷新，不额外起进程）
    aggregator.service = service
    return Container(
        settings=settings,
        runner=runner,
        client=client,
        slots=slots,
        props=props,
        gpu=gpu,
        system=system,
        metrics=metrics,
        journal=journal,
        alerts=alerts,
        history=history,
        aggregator=aggregator,
        hub=hub,
        service=service,
        hardware=hardware,
        baselines=baselines,
        alert_log=alert_log,
        log_history=log_history,
    )


async def _tick_loop(c: Container) -> None:
    """采集节拍：并发采集 → 聚合 → 广播（方案 5.5）。"""
    s = c.settings
    last_fw_check = 0.0
    while True:
        t0 = time.monotonic()
        try:
            # v0.5：识别未知时按间隔重试 —— 覆盖"先起控制台、后起推理服务"
            # 以及"换了框架重启服务"的场景。已识别成功则不再重复探测。
            if (c.framework is None or c.framework.confidence == "unknown") and (
                t0 - last_fw_check >= s.framework_redetect_s
            ):
                last_fw_check = t0
                await _detect_framework_task(c)
            snap = await c.aggregator.tick(ws_clients=c.hub.client_count, ws_stats=c.hub.stats())
            c.tick_count += 1
            c.last_tick_ts = time.time()
            c.history.add(snap)
            c.hub.broadcast_snapshot(snap)
            for a in snap.alerts:
                c.hub.broadcast_alert(a)
            while c.alerts.resolved_events:
                c.hub.broadcast_alert(c.alerts.resolved_events.pop(0), resolved=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 采集循环必须自愈
            log.warning("tick failed: %s: %s", type(exc).__name__, exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(s.poll_interval_s - elapsed, 0.05))


async def _warm_history_cache(c: Container) -> None:
    """后台预热历史日志缓存（v0.4.3）。

    不阻塞启动：即使 journald 很慢或不可用，也只是少一次预热，
    页面仍可正常按需查询。
    """
    try:
        res = await c.log_history.fetch(days=None)  # 默认档位（30 天）
        log.info(
            "history cache warmed: %s days, %d lines in %.0f ms",
            res.requested_days,
            res.returned,
            res.elapsed_ms,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 预热失败不影响服务
        log.debug("history warmup skipped: %s", exc)


async def _detect_framework_task(c: Container) -> None:
    """启动时识别推理框架，并按识别结果开关采集能力（v0.5 第 1 步）。

    不阻塞启动：识别失败只是少一次能力裁剪，采集循环照常运行。
    之后每个采集节拍会按 ``framework_redetect_s`` 限流重试，
    这样"先起控制台、后起推理服务"的顺序也能最终识别正确。
    """
    try:
        info = await detect_framework(c.client.probe)
        c.aggregator.set_framework(info)
        if info.confidence == "unknown":
            log.warning(
                "inference framework not identified yet; will retry (probes=%s)",
                info.probes,
            )
        else:
            log.info("framework: %s", fw_summary(info))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 识别失败不影响服务
        log.warning("framework detection failed: %s: %s", type(exc).__name__, exc)


def fw_summary(info: FrameworkInfo) -> str:
    from .services.framework import capability_summary

    return capability_summary(info)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    c = build_container(settings)
    app.state.ctx = c

    tasks: list[asyncio.Task] = []
    c.system.warmup()
    # v0.5 第 1 步：先识别推理框架，再决定各接口是否可用。
    # 放在 props 采集之前 —— 否则在 ollama/vLLM 上会先白跑一轮失败的探测。
    await _detect_framework_task(c)
    await c.props.collect(force=True)  # 首屏必须有 KV 分母与配置徽标
    c.aggregator.set_unit_config(load_unit_config(settings))
    await c.journal.start()
    tasks.append(asyncio.create_task(_tick_loop(c), name="tick-loop"))
    await c.watchdog.start()
    await c.service.check_authorization()
    await c.service.status()
    c.tasks = tasks
    # v0.4.3：预热默认档位的历史日志缓存。
    # 实测 30 天查询约 5.3s（journalctl 格式化 1 万行的成本），后台跑，
    # 让第一个打开历史日志页的用户直接命中缓存，而不是干等 5 秒。
    tasks.append(asyncio.create_task(_warm_history_cache(c), name="history-warmup"))
    notify.ready()
    notify.status(f"{settings.product_name} 就绪，监听 {settings.host}:{settings.port}")
    log.info(
        "%s 启动：监听 %s:%s，被监控单元 %s，metrics=%s",
        settings.product_name,
        settings.host,
        settings.port,
        settings.llama_unit,
        c.props.metrics_enabled,
    )
    try:
        yield
    finally:
        notify.stopping()
        for t in tasks:
            t.cancel()
        # cancel 之后必须 await，否则会残留 journalctl 子进程（12.7 第 6 条）
        await asyncio.gather(*tasks, return_exceptions=True)
        await c.watchdog.stop()
        await c.journal.stop()
        await c.client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is not None:
        import app.config as cfg

        cfg._settings = settings  # noqa: SLF001 - 测试注入
    s = settings or get_settings()
    app = FastAPI(
        title=f"{s.product_name} API", version="0.1.0", lifespan=lifespan, docs_url="/docs", redoc_url=None
    )
    routes.register(app)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> JSONResponse:
        # 全站零图片资源：不返回图标文件，而是 204
        return JSONResponse(status_code=204, content=None)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover
        log.error("unhandled error on %s: %s: %s", request.url.path, type(exc).__name__, exc)
        return JSONResponse({"error": "internal", "path": request.url.path}, status_code=500)

    @app.websocket("/ws/metrics")
    async def ws_metrics(ws: WebSocket) -> None:
        c: Container = ws.app.state.ctx
        await c.hub.handle_metrics(ws, lambda: c.aggregator.snapshot)

    @app.websocket("/ws/logs")
    async def ws_logs(ws: WebSocket) -> None:
        c: Container = ws.app.state.ctx
        await c.hub.handle_logs(ws, c.journal)

    static_dir = s.static_dir
    if not os.path.isabs(static_dir):
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), static_dir)
    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:  # pragma: no cover - 由 StaticFiles 处理
            return FileResponse(os.path.join(static_dir, "index.html"))
    else:  # pragma: no cover
        log.warning("static dir not found: %s", static_dir)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    st = get_settings()
    uvicorn.run(
        "app.main:app",
        host=st.host,
        port=st.port,
        workers=1,
        timeout_graceful_shutdown=30,
        access_log=False,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
