"""日志派生指标（方案 6.2.1 / 6.2.3 / 6.2.4）。

由 JournalFollower 每解析一行就调用一次 ``update()``，滚动维护：
  * 实时解码速率（tg_3s > tg > 差分）
  * 上下文填充速度（prompt eval time）
  * MTP 接受率与 draft 平均长度
  * 最近请求明细（由一组 print_timing 行聚合成一条快照）
  * 关键事件计数（退出 / 取消 / 截断）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..collectors.logregex import parse_all
from ..models import RecentRequest


@dataclass
class LogStats:
    # 实时解码速率
    decode_tps: float | None = None
    decode_tps_source: str = "none"  # tg_3s / tg / none
    n_gen: int | None = None
    # 上下文填充速度
    prefill_tps: float | None = None
    prefill_tokens: int | None = None
    # 最近一次生成完成
    eval_tps: float | None = None
    eval_tokens: int | None = None
    total_time_ms: float | None = None
    total_tokens: int | None = None
    # MTP
    mtp_accept: float | None = None
    mtp_accepted: int | None = None
    mtp_generated: int | None = None
    draft_mean_len: float | None = None
    # 生命周期与事件
    last_acceptance_ts: float = 0.0
    last_progress_ts: float = 0.0
    last_prefill_ts: float = 0.0
    model_loaded_ts: float = 0.0
    last_exit_status: int | None = None
    last_exit_ts: float = 0.0
    truncated_events: int = 0
    cancel_events: int = 0
    exit_events: int = 0
    last_release_tokens: int | None = None
    acked_lines: int = 0
    # 最近请求明细
    recent: RecentRequest = field(default_factory=RecentRequest)

    def update(self, text: str, epoch: float | None = None) -> None:
        """解析一行日志并滚动更新。永不抛异常。"""
        ts = epoch if epoch else time.time()

        # 【回归修复】取消事件必须在 parse_all 之前判断。
        # 实测踩过的坑：llama.cpp 的取消行形如
        #   ``206.40.125.385 W srv stop: cancel task, id_task = 47734``
        # 它**不含**其它任何可识别字段，parse_all 返回空字典，
        # 下面的 ``if not fields: return`` 会提前返回 —— 导致取消计数
        # 永远不增长，CLIENT_CANCEL 告警自 v0.1 起从未真正触发过。
        # （由 v0.4.3 的告警日志功能暴露：端到端测试发现"取消后无记录"。）
        if "cancel task" in text:
            self.cancel_events += 1

        try:
            fields = parse_all(text)
        except Exception:  # noqa: BLE001
            return
        if not fields:
            return
        self.acked_lines += 1

        if "progress" in fields:
            p = fields["progress"]
            self.n_gen = p["n_gen"]
            self.decode_tps = p["tg_3s"]
            self.decode_tps_source = "tg_3s"
            self.last_progress_ts = ts

        if "prefill" in fields:
            pf = fields["prefill"]
            self.prefill_tps = pf["tps"]
            self.prefill_tokens = pf["tokens"]
            self.last_prefill_ts = ts

        if "eval" in fields:
            ev = fields["eval"]
            self.eval_tps = ev["tps"]
            self.eval_tokens = ev["tokens"]

        if "total_time" in fields:
            self.total_time_ms = fields["total_time"]["ms"]
            self.total_tokens = fields["total_time"]["tokens"]

        if "acceptance" in fields:
            ac = fields["acceptance"]
            self.mtp_accept = ac["ratio"] if ac["ratio"] is not None else ac["rate"]
            self.mtp_accepted = ac["accepted"]
            self.mtp_generated = ac["generated"]
            self.draft_mean_len = ac["mean_len"]
            self.last_acceptance_ts = ts
            self._compose_recent(ts)

        if "release" in fields:
            self.last_release_tokens = fields["release"]["n_tokens"]
            if fields["release"]["truncated"]:
                self.truncated_events += 1

        if "exit" in fields:
            self.last_exit_status = fields["exit"]["status"]
            self.last_exit_ts = ts
            self.exit_events += 1

        if fields.get("model_loaded"):
            self.model_loaded_ts = ts

    def _compose_recent(self, ts: float) -> None:
        self.recent = RecentRequest(
            prefill_tps=self.prefill_tps,
            prefill_tokens=self.prefill_tokens,
            decode_tps=self.eval_tps,
            decode_tokens=self.eval_tokens,
            total_tokens=self.total_tokens,
            mtp_accept=self.mtp_accept,
            draft_mean_len=self.draft_mean_len,
            ts=ts,
        )

    def idle_seconds(self) -> float:
        """距最近一次生成活动的秒数，用于判断「空闲」以回退速率来源。"""
        if not self.last_progress_ts:
            return 1e9
        return time.time() - self.last_progress_ts

    def effective_decode_tps(self, fallback: float | None) -> tuple[float | None, str]:
        """解码速率取值优先级：tg_3s > tg > /slots 差分（方案 6.2.1）。"""
        if self.decode_tps is not None and self.idle_seconds() < 15:
            return self.decode_tps, self.decode_tps_source
        if fallback is not None:
            return fallback, "slots_delta"
        if self.decode_tps is not None:
            return self.decode_tps, self.decode_tps_source + "_stale"
        return None, "none"
