"""指标聚合器（方案 TASK-10 / 6.2.1）。

**全部 21 项公式集中在此模块实现，前端不得重复计算任何公式。**

数据源代号：A /slots、B journald、C nvidia-smi、D /props 与 /v1/models、
E /metrics、F psutil。
"""

from __future__ import annotations

import logging
import time

from ..collectors.gpu import GpuCollector
from ..collectors.hardware import HardwareCollector
from ..collectors.journal import JournalFollower
from ..collectors.prometheus import PrometheusCollector
from ..collectors.props import PropsCollector
from ..collectors.slots import SlotsCollector
from ..collectors.system import SystemCollector
from ..config import Settings
from ..models import AccelBadge, KpiBlock, MetricSnapshot
from ..payload import branding_of, health_of, thresholds_of
from . import accel, gpu_spec, kvmode
from . import framework as fw
from .alerts import AlertEngine
from .baseline import BaselineLearner
from .framework import FrameworkInfo
from .service_ctl import ServiceController
from .unitinfo import UnitConfig

log = logging.getLogger("llmconsole.aggregator")


class Aggregator:
    def __init__(
        self,
        settings: Settings,
        *,
        slots: SlotsCollector,
        props: PropsCollector,
        gpu: GpuCollector,
        system: SystemCollector,
        metrics: PrometheusCollector,
        journal: JournalFollower,
        alerts: AlertEngine,
        hardware: HardwareCollector | None = None,
        baselines: BaselineLearner | None = None,
    ):
        self.s = settings
        self.slots = slots
        self.props = props
        self.gpu = gpu
        self.system = system
        self.metrics = metrics
        self.journal = journal
        self.alerts = alerts
        self.hardware = hardware
        self.baselines = baselines
        self.seq = 0
        self.snapshot = MetricSnapshot()
        self.draft_n_max = 0
        self.unit_cfg = UnitConfig()
        self._seen_events = {"exit": 0, "truncated": 0, "cancel": 0}
        #: v0.4：被监控服务运行时长（由 ServiceController 限流刷新）
        self.service: ServiceController | None = None
        self._svc_uptime: float | None = None
        self._svc_last_mono: float = 0.0
        self._llama_start_ts: float | None = None
        #: v0.5：推理框架识别结果（llama.cpp / ollama / vLLM / SGLang / …）
        self.framework: FrameworkInfo | None = None

    # ------------------------------------------------------------------
    def set_framework(self, info: FrameworkInfo) -> None:
        """注入推理框架识别结果，并据此**开关各采集器的能力**。

        这是 v0.5 可移植性的关键：换一个框架部署时，
        不支持的接口应当"明确不采集"，而不是"采集失败 → 界面降级"。
        """
        self.framework = info
        self.slots.set_supported(fw.supports(info, fw.CAP_SLOTS))
        self.props.set_capabilities(
            fw.supports(info, fw.CAP_PROPS),
            fw.supports(info, fw.CAP_MODELS),
        )
        # v0.6.1：指标名随框架切换（llamacpp: / vllm: / sglang:）。
        # 是否真的采集由 _collect_all() 每拍结合 /props 决定，这里只同步名字表。
        self.metrics.set_series_map(info.metrics_map)
        self.metrics.set_endpoint_enabled(fw.supports(info, fw.CAP_METRICS), self._metrics_disabled_reason())

    # ------------------------------------------------------------------
    def _metrics_enabled(self) -> bool:
        """本拍是否应采集 ``/metrics``（框架能力 + ``/props`` 开关共同决定）。

        规则：
          * 尚未识别框架 → 只看 ``/props``（保持历史行为，llama.cpp 老路径）；
          * 框架不支持 ``CAP_METRICS`` → 不采集（如 Ollama 没有 Prometheus 接口）；
          * 框架支持且有 ``/props``（llama.cpp）→ ``/props`` 的 endpoint_metrics 是权威开关；
          * 框架支持但没有 ``/props``（vLLM / SGLang）→ 默认开启（它们的 /metrics 常开）。

        **这是 v0.6.1 修复的缺陷点**：原先 ``_collect_all()`` 直接用
        ``self.props.metrics_enabled`` 覆盖了 ``set_framework()`` 里按能力做出的
        判断，而 vLLM/SGLang 没有 ``/props``，该值恒为 False —— 于是即便框架
        声明了 ``CAP_METRICS``，``/metrics`` 也永远不会被采集。
        """
        info = self.framework
        if info is None:
            return self.props.metrics_enabled
        if not fw.supports(info, fw.CAP_METRICS):
            return False
        if fw.supports(info, fw.CAP_PROPS):
            return self.props.metrics_enabled
        return True

    def _metrics_disabled_reason(self) -> str | None:
        """不可采集时给用户的**具体**原因（``None`` = 用采集器默认文案）。"""
        info = self.framework
        if info is not None and not fw.supports(info, fw.CAP_METRICS):
            return f"当前推理框架（{info.id}）不提供 Prometheus 指标接口"
        return None

    def framework_dict(self) -> dict:
        if self.framework is None:
            return {}
        return self.framework.as_dict()

    def set_unit_config(self, cfg: UnitConfig) -> None:
        """注入 systemd unit 的真实运行参数（比 /props 默认值权威）。"""
        self.unit_cfg = cfg
        self.draft_n_max = cfg.draft_n_max

    def _sync_log_events(self) -> None:
        """把日志里的事件计数转成告警（TASK-20 规则 2/10/11）。"""
        st = self.journal.stats
        cur = {"exit": st.exit_events, "truncated": st.truncated_events, "cancel": st.cancel_events}
        if cur["exit"] != self._seen_events["exit"]:
            self.alerts.note_exit(st.last_exit_status if st.last_exit_status is not None else -1)
        if cur["truncated"] != self._seen_events["truncated"]:
            self.alerts.note_truncated()
        if cur["cancel"] != self._seen_events["cancel"]:
            self.alerts.note_cancel()
        self._seen_events = cur

    # ------------------------------------------------------------------
    async def tick(self, ws_clients: int = 0, ws_stats: dict | None = None) -> MetricSnapshot:
        """一个采集节拍：并发采集 → 归并 → 公式 → 告警。

        ``ws_stats`` 是 WebSocket Hub 的连接统计（``hub.stats()``），只用于
        快照里的 ``health.ws``。聚合器**不持有** Hub，因此由采集循环传入。
        """
        await self._collect_all()
        self._sync_log_events()
        snap = self._build(ws_clients, ws_stats)
        snap.alerts = self.alerts.evaluate(snap)
        self.snapshot = snap
        return snap

    async def _collect_all(self) -> None:
        import asyncio

        tasks = [self.slots.collect(), self.gpu.collect()]
        await asyncio.gather(*tasks, return_exceptions=True)
        # psutil 是同步阻塞但 <5ms，直接调用（方案 TASK-07 实现要点 5）
        self.system.collect()
        if self.props.due():
            await self.props.collect()
        # 让采集器跟随 /props 的状态：服务端加上 --metrics 并重启后，
        # 控制台必须自己恢复，而不是一直停在「未启用」（实测踩过这个坑）。
        #
        # v0.6.1：这里的开关必须同时考虑**框架能力** —— 原先只用
        # ``self.props.metrics_enabled`` 覆盖，会在 vLLM/SGLang（没有 /props）
        # 上把 CAP_METRICS 的判断抹掉，导致 /metrics 永不采集。
        enabled = self._metrics_enabled()
        self.metrics.set_endpoint_enabled(enabled, self._metrics_disabled_reason())
        if enabled:
            await self.metrics.collect()
        if self.slots.total_ctx == 0 and self.props.total_ctx:
            self.slots.total_ctx = self.props.total_ctx
        # v0.4 §5：硬件清点按 TTL 触发（默认 600s），**绝不进 2 秒节拍**
        if self.hardware is not None and self.hardware.due():
            await self.hardware.collect()
        # v0.4 决策 B1：服务运行时长的刷新单独限流（默认 30s）
        await self._refresh_service_uptime()

    # ------------------------------------------------------------------
    def _kv_block(self):
        """按运行时探测结果构造 KV 块（v0.4 §5.3/§5.4，修复 F14/F15/F16）。

        容量与模式来自 ``kvmode.decide()``：unit 的 ``-c`` 作总预算、
        ``-kvu`` 定模式、journal 启动日志兜底，都拿不到则标记 unknown（不猜）。
        """
        unit = self.unit_cfg
        journal_text = "\n".join(ln.text for ln in self.journal.recent(300))
        cap = kvmode.decide(
            slot_ctxs=[s.n_ctx for s in self.slots.slots],
            unit_ctx=unit.n_ctx,
            kv_unified=unit.kv_unified if unit.readable else None,
            journal_text=journal_text,
            override=self.s.kv_mode_override,
        )
        # 兜底：unit 与 journal 都拿不到时，用 /props 的每槽 n_ctx 至少把
        # 单池容量显示出来（模式仍标 unknown，不假装知道）
        if cap.total_tokens == 0 and self.props.total_ctx:
            cap = kvmode.KvCapacity(total_tokens=self.props.total_ctx, mode="unknown", source="props")
        return self.slots.kv_block(
            cap,
            quant=(unit.cache_type_k, unit.cache_type_v),
            show_default_quant=self.s.kv_quant_show_default,
        )

    # ------------------------------------------------------------------
    def _build(self, ws_clients: int, ws_stats: dict | None = None) -> MetricSnapshot:
        self.seq += 1
        now = time.time()
        st = self.journal.stats

        kv = self._kv_block()

        decode_tps, decode_src = st.effective_decode_tps(self.slots.slots_delta_tps)

        # 累计生成 token：优先 /metrics（精确），否则回退日志累加（不精确）
        gen_total = self.metrics.tokens_predicted_total()
        gen_exact = gen_total is not None
        if gen_total is None:
            gen_total = self._generated_from_logs()

        mtp = st.mtp_accept if st.mtp_accept is not None else self.metrics.mtp_accept()

        kpi = KpiBlock(
            decode_tps=decode_tps,
            decode_tps_source=decode_src,
            prefill_tps=st.prefill_tps,
            mtp_accept=mtp,
            draft_mean_len=st.draft_mean_len,
            processing=self.slots.processing_count(),
            slots_total=self.slots.slots_total or int(self.props.props.get("total_slots") or 0),
            deferred=self.metrics.requests_deferred(),
            vram_used_mib=self.gpu.vram_used_mib(),
            vram_total_mib=self.gpu.vram_total_mib(),
            generated_total=gen_total,
            generated_total_exact=gen_exact,
            recent=st.recent,
        )

        stale = {
            "slots": self.slots.state.stale,
            "gpu": self.gpu.state.stale,
            "sys": self.system.state.stale,
            "config": self.props.state.stale,
            "metrics": self.metrics.available is False or self.metrics.state.stale,
            "logs": (time.time() - self.journal.last_line_ts) > 120 if self.journal.last_line_ts else True,
        }

        # v0.4 §7：喂给自动基线学习器（学习期内样本被丢弃）
        if self.baselines is not None:
            self.baselines.observe(mtp, decode_tps if decode_src != "none" else None)

        gpus = self.gpu.gpus
        gpu0 = gpus[0].name if gpus else ""
        base_state = self.baselines.state() if self.baselines else None

        return MetricSnapshot(
            seq=self.seq,
            ts=now,
            stale=stale,
            model=self.props.model,
            kpi=kpi,
            kv=kv,
            gpus=gpus,
            system=self.system.info,
            self_info=self.system.self_info(ws_clients),
            runtime=self.props.runtime_config(
                len(gpus), self.unit_cfg, self._slot_spec_types(), gpu0, self._platform()
            ),
            alerts=[],
            baseline=base_state if base_state is not None else MetricSnapshot().baseline,
            accelerator_badge=self._accel_badge(gpus),
            llama_uptime_s=self._llama_uptime(),
            hardware_ts=self.hardware.info.collected_ts if self.hardware else 0.0,
            #: v0.5：框架信息随快照下发。
            #: **必须在这里**，否则 REST 有、WebSocket 没有 ——
            #: 页面每 2 秒被推送覆盖一次，徽标会先对一瞬再退回占位。
            framework=self.framework_dict(),
            #: v0.6.1：阈值/品牌/健康度也必须在这里（同一个根因，同一条规则）。
            #: 全部走 ``app/payload.py``，与 ``/api/overview`` 是同一份构造逻辑；
            #: 若只挂在路由上，页面每 2 秒被推送覆盖后阈值会变成空字典
            #: （前端退回硬编码 95/85/87/83），降级横幅也会静默消失。
            thresholds=self._thresholds(),
            branding=branding_of(self.s),
            health=health_of(self, ws_stats),
        )

    # ------------------------------------------------------------------
    def _thresholds(self) -> dict:
        """阈值块（F5：前端不得硬编码）。"""
        return thresholds_of(self.s, self.baselines)

    # ------------------------------------------------------------------
    def _platform(self) -> str:
        """平台文案：按**实际探测到的**算力卡厂家给出，不写死 NVIDIA。"""
        info = self.hardware.snapshot() if self.hardware else None
        if info and info.vendors:
            return " / ".join(accel.VENDOR_DISPLAY.get(v, v.upper()) for v in info.vendors)
        return ""

    def _accel_badge(self, gpus) -> AccelBadge:
        """顶栏标识1 的算力卡摘要（v0.4 R1）——从实测结果生成。"""
        if not gpus:
            return AccelBadge(present=False, text="未检测到算力卡")
        name = gpus[0].name or ""
        vendor = gpus[0].vendor or gpu_spec.vendor_of(name) or "unknown"
        return AccelBadge(
            present=True,
            vendor=accel.VENDOR_DISPLAY.get(vendor, vendor.upper()),
            model=name,
            count=len(gpus),
            tensor_parallel=self.unit_cfg.tensor_parallel,
            text=accel.badge_text(vendor, name, len(gpus)),
        )

    def _llama_uptime(self) -> float | None:
        """llama-server 运行时长（顶栏「服务运行」，v0.4 决策 B1）。

        优先用 systemd 的 ``ActiveEnterTimestampMonotonic``（由
        ``_refresh_service_uptime`` 定期刷新）；拿不到时回退 journal 里
        最近一条 ``model loaded``；都没有则返回 None（界面显示「—」，不编造）。
        """
        if self._svc_uptime is not None:
            return self._svc_uptime
        ts = getattr(self.journal.stats, "model_loaded_ts", 0.0)
        if not ts:
            return None
        delta = time.time() - ts
        return round(delta, 1) if delta >= 0 else None

    async def _refresh_service_uptime(self) -> None:
        """按 ``service_poll_interval_s`` 刷新被监控服务的运行时长。

        单独限流是因为它要起一次 ``systemctl show``（约 10ms），
        没必要放进 2 秒的采集节拍里。
        """
        if self.service is None:
            return
        now = time.monotonic()
        if now - self._svc_last_mono < self.s.service_poll_interval_s:
            return
        self._svc_last_mono = now
        try:
            st = await self.service.status()
            self._svc_uptime = st.uptime_s
        except Exception as exc:  # noqa: BLE001 - 运行时长拿不到不该影响采集
            log.debug("service uptime refresh failed: %s", exc)

    def _slot_spec_types(self) -> str:
        """取 /slots 上真实生效的投机解码类型。

        注意：槽位空闲时 ``params`` 里没有 ``speculative.types``（实测为 None），
        而且有的槽位只报 ``"none"``。因此优先挑含实际投机类型的值。
        """
        vals = [s.speculative_types for s in self.slots.slots if s.speculative_types]
        if not vals:
            return ""
        for v in vals:
            low = v.lower()
            if "draft" in low or "mtp" in low:
                return v
        return vals[0]

    def _generated_from_logs(self) -> int | None:
        """无 /metrics 时的回退：累加 stop processing 的 n_tokens（含 prompt，不精确）。"""
        v = self.journal.stats.last_release_tokens
        return v if v else None

    # ------------------------------------------------------------------
    def health(self) -> dict:
        j = self.journal
        return {
            "llama_server": {
                "ok": not self.slots.state.stale,
                "url": self.s.health_url,
                "last_ok_age_s": round(self.slots.state.age_s, 1)
                if self.slots.state.age_s is not None
                else None,
                "error": self.slots.state.last_error,
            },
            "nvidia_smi": {
                "ok": not self.gpu.state.stale,
                "avg_ms": round(self.gpu.state.avg_ms, 1),
                "error": self.gpu.state.last_error,
            },
            "journald": {
                "ok": j.running,
                "unit": self.s.llama_unit,
                "lines_total": j.lines_total,
                "restarts": j.restarts,
                "error": None if j.running else "follower not running",
            },
            "metrics": {
                "ok": self.metrics.available is True,
                "enabled": self._metrics_enabled(),
                "reason": self.metrics.disabled_reason,
            },
            "collectors": {
                "slots": self.slots.state.as_dict(),
                "gpu": self.gpu.state.as_dict(),
                "sys": self.system.state.as_dict(),
                "config": self.props.state.as_dict(),
                "metrics": self.metrics.state.as_dict(),
            },
        }

    def ready(self) -> tuple[bool, list[str]]:
        """readiness：只读各数据源的最近成功时间，不做实时探测（方案 TASK-13）。"""
        reasons: list[str] = []
        if self.slots.state.stale:
            reasons.append(f"llama-server /slots 不可用（{self.slots.state.last_error or 'unknown'}）")
        if self.gpu.state.stale:
            reasons.append(f"nvidia-smi 不可用（{self.gpu.state.last_error or 'unknown'}）")
        if not self.journal.running:
            reasons.append("journalctl 跟随器未运行")
        return (len(reasons) == 0), reasons

    def ready_codes(self) -> tuple[bool, list[str]]:
        """readiness 的**语言无关**版本（v0.4.3 §6.4）。

        前端按 ``reason_codes`` 本地化提示；``ready()`` 的中文串保留作兼容。
        """
        codes: list[str] = []
        if self.slots.state.stale:
            codes.append("slots_unavailable")
        if self.gpu.state.stale:
            codes.append("gpu_unavailable")
        if not self.journal.running:
            codes.append("journal_not_running")
        return (len(codes) == 0), codes
