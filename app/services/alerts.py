"""告警引擎（方案 TASK-20 / 6.3.4）——11 条规则 + 去抖。

设计：
  * 阈值类告警必须「持续 N 秒」才触发，避免秒级抖动；去抖状态机可单测；
  * MTP 接受率与解码吞吐的基线**不再写死**（v0.4 §7 / F4），
    改由 ``BaselineLearner`` 运行时自动学习；学习期未就绪则不判该条告警；
  * 功耗告警相对**每张卡自己的 power_limit**（v0.4 F7）；
  * 三级：critical（红）/ warning（橙）/ info（灰）；
  * 恢复时产生 resolved 事件，界面据此撤下。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..config import Settings
from ..models import Alert, MetricSnapshot
from .alert_log import AlertLog

if TYPE_CHECKING:  # 避免运行期循环导入
    from .baseline import BaselineLearner

LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


class _Debounce:
    """「持续 N 秒才算数」的状态机。"""

    def __init__(self, sustain_s: float):
        self.sustain_s = sustain_s
        self.since: float | None = None

    def update(self, active: bool, now: float) -> bool:
        if not active:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return (now - self.since) >= self.sustain_s

    def reset(self) -> None:
        self.since = None

    @property
    def value_since(self) -> float:
        return self.since or time.time()


class AlertEngine:
    def __init__(
        self,
        settings: Settings,
        baselines: BaselineLearner | None = None,
        alert_log: AlertLog | None = None,
    ):
        self.s = settings
        #: v0.4 §7：自动基线学习器；为 None 时退回配置里的人工覆盖值
        self.baselines = baselines
        #: v0.4.3 §6.1：告警日志（记录产生/恢复事件，供独立页面查询）
        self.alert_log = alert_log
        self._db: dict[str, _Debounce] = {}
        self.active: dict[str, Alert] = {}
        self.resolved_events: list[Alert] = []
        self._down_misses = 0
        self._event_alerts: dict[str, tuple[str, str]] = {}
        self._event_since: dict[str, float] = {}

    def _d(self, code: str, sustain_s: float) -> _Debounce:
        if code not in self._db:
            self._db[code] = _Debounce(sustain_s)
        return self._db[code]

    # ------------------------------------------------------------------
    def evaluate(self, snap: MetricSnapshot) -> list[Alert]:
        now = time.time()
        found: dict[str, Alert] = {}

        def raise_alert(
            code: str, level: str, message: str, value: float | None = None, detail: str = ""
        ) -> None:
            prev = self.active.get(code)
            since = prev.since if prev else self._db[code].value_since if code in self._db else now
            found[code] = Alert(
                code=code, level=level, message=message, since=since, value=value, detail=detail
            )

        # 1. 服务不可达
        if snap.stale.get("slots"):
            self._down_misses += 1
        else:
            self._down_misses = 0
        if self._down_misses >= self.s.service_down_ticks:
            raise_alert(
                "SERVICE_DOWN",
                "critical",
                "llama-server 不可达",
                detail=f"连续 {self._down_misses} 拍采集失败",
            )

        # 3. GPU 过热
        tmax = max((g.temp_c for g in snap.gpus if g.temp_c is not None), default=None)
        if tmax is not None:
            if tmax > self.s.gpu_temp_crit_c:
                raise_alert(
                    "GPU_TEMP_CRIT",
                    "critical",
                    f"GPU 温度 {tmax:.0f} °C 超过 {self.s.gpu_temp_crit_c:.0f} °C",
                    tmax,
                )
            elif self._d("GPU_TEMP_WARN", self.s.gpu_temp_sustain_s).update(
                tmax > self.s.gpu_temp_warn_c, now
            ):
                raise_alert(
                    "GPU_TEMP_WARN", "warning", f"GPU 温度持续高于 {self.s.gpu_temp_warn_c:.0f} °C", tmax
                )

        # 4. 显存高水位
        used, total = snap.kpi.vram_used_mib, snap.kpi.vram_total_mib
        if used is not None and total:
            pct = used / total * 100.0
            if pct > self.s.vram_crit_pct:
                raise_alert(
                    "VRAM_CRIT", "critical", f"显存占用 {pct:.1f}% 超过 {self.s.vram_crit_pct:.0f}%", pct
                )
            elif pct > self.s.vram_warn_pct:
                raise_alert("VRAM_WARN", "warning", f"显存占用 {pct:.1f}% 偏高", pct)

        # 5. KV 池将满
        if snap.kv.pct is not None:
            if snap.kv.pct > self.s.kv_crit_pct:
                raise_alert(
                    "KV_CRIT",
                    "critical",
                    f"KV 池占用 {snap.kv.pct:.1f}% 超过 {self.s.kv_crit_pct:.0f}%",
                    snap.kv.pct,
                )
            elif self._d("KV_WARN", self.s.kv_sustain_s).update(snap.kv.pct > self.s.kv_warn_pct, now):
                raise_alert("KV_WARN", "warning", f"KV 池占用持续高于 {self.s.kv_warn_pct:.0f}%", snap.kv.pct)

        # 6. 功耗异常 —— v0.4 F7：相对**每张卡自己的 power_limit** 判定，
        # 不再用写死的绝对瓦数（V100 300W 与 4090 450W 都适用）
        for g in snap.gpus:
            if g.power_w is None or not g.power_limit_w:
                continue
            ppct = g.power_w / g.power_limit_w * 100.0
            if ppct > self.s.power_warn_pct:
                raise_alert(
                    "GPU_POWER",
                    "info",
                    f"GPU{g.index} 功耗 {g.power_w:.0f} W（达上限 {ppct:.0f}%）",
                    g.power_w,
                )
                break

        # 7. 请求排队（依赖 /metrics）
        if snap.kpi.deferred and self._d("REQ_DEFERRED", self.s.deferred_sustain_s).update(
            snap.kpi.deferred > 0, now
        ):
            raise_alert(
                "REQ_DEFERRED", "warning", f"有 {int(snap.kpi.deferred)} 个请求排队", snap.kpi.deferred
            )

        # 8. MTP 接受率下滑 —— v0.4 F4：基线来自自动学习，未就绪则不判
        if snap.kpi.mtp_accept is not None:
            base = self.baselines.mtp_baseline if self.baselines else self.s.mtp_accept_baseline
            if base:
                floor = base * self.s.mtp_drop_ratio
                if self._d("MTP_LOW", self.s.mtp_sustain_s).update(snap.kpi.mtp_accept < floor, now):
                    raise_alert(
                        "MTP_LOW",
                        "warning",
                        f"MTP 接受率 {snap.kpi.mtp_accept * 100:.1f}% 低于基线 {floor * 100:.0f}%",
                        snap.kpi.mtp_accept,
                    )

        # 9. 解码吞吐下滑
        if snap.kpi.decode_tps is not None and snap.kpi.processing > 0:
            base = self.baselines.decode_baseline if self.baselines else self.s.decode_baseline_tps
            if base:
                floor = base * self.s.decode_drop_ratio
                if self._d("DECODE_LOW", self.s.decode_sustain_s).update(snap.kpi.decode_tps < floor, now):
                    raise_alert(
                        "DECODE_LOW",
                        "warning",
                        f"解码速率 {snap.kpi.decode_tps:.1f} t/s 低于基线 {floor:.0f} t/s",
                        snap.kpi.decode_tps,
                    )

        # 10 / 11. 截断与取消由日志事件驱动（在 note_* 中登记）
        #
        # 【v0.4.3 修复】事件型告警是**瞬时**的：过去没有任何地方清除
        # ``_event_alerts``，一旦发生过一次取消，界面会永久挂着"客户端取消"，
        # 告警日志也永远只有 raised 没有 resolved。
        # 现在改为保留 ``event_alert_ttl_s`` 秒后自动清除 → 自然产生恢复事件。
        # （该缺陷自 v0.1 起潜伏，因取消计数本身是坏的所以从未显现；
        #   修好计数后才暴露出来。）
        ttl = float(self.s.event_alert_ttl_s)
        for code, (level, msg) in list(self._event_alerts.items()):
            since = self._event_since.get(code, now)
            if ttl > 0 and (now - since) > ttl:
                self.clear_event(code)
                continue
            found[code] = Alert(code=code, level=level, message=msg, since=since)

        # 计算 resolved
        for code in list(self.active):
            if code not in found:
                self.resolved_events.append(self.active[code])
                if code in self._db:
                    self._db[code].reset()
        self.active = found
        # v0.4.3 §6.1：把状态差异写进告警日志（新出现的→raised，消失的→resolved）。
        # 状态差量语义保证同一告警持续期间不会重复记录，天然被去抖抑制。
        if self.alert_log is not None:
            self.alert_log.sync(found, now)
        return sorted(found.values(), key=lambda a: (LEVEL_ORDER.get(a.level, 9), a.code))

    # ------------------------------------------------------------------
    # 事件型告警：每次发生都**刷新保留窗口**（赋值而非 setdefault），
    # 这样持续发生的取消/截断保持告警，停止后经过 TTL 自动恢复。
    def note_exit(self, status: int) -> None:
        self._event_alerts["PROC_EXIT"] = ("critical", f"llama-server 进程退出（status={status}）")
        self._event_since["PROC_EXIT"] = time.time()

    def note_truncated(self) -> None:
        self._event_alerts["CTX_TRUNCATED"] = ("warning", "请求上下文被截断（truncated=1）")
        self._event_since["CTX_TRUNCATED"] = time.time()

    def note_cancel(self) -> None:
        self._event_alerts["CLIENT_CANCEL"] = ("info", "客户端取消了生成任务")
        self._event_since["CLIENT_CANCEL"] = time.time()

    def clear_event(self, code: str) -> None:
        self._event_alerts.pop(code, None)
        self._event_since.pop(code, None)
