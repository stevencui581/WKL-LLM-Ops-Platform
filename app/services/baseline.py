"""自动基线学习器（v0.4 §7 / TASK-31 / F4 修复）。

v0.1 把 MTP 接受率与解码吞吐的基线**写死**为 目标 的实测值（0.818 / 68.0 t/s），
换服务器或换模型后必然误告警。本模块改为**运行时自动学习**：

    部署 → 运行 → 采样学习 → 建立基线 → 冻结 → 用基线判告警

设计要点：
  * 学习期（``baseline_warmup_s`` 之前）**不采信**任何样本，避开冷启动；
  * 样本数达到 ``baseline_min_samples`` 后取分位数（默认中位数）作为基线并冻结；
  * 基线落盘 ``state/baseline.json``，控制台重启后复用，不重复学习；
  * 默认**不重学**，避免基线跟着性能劣化一起下滑从而掩盖真实故障；
  * 允许环境变量人工覆盖（``LLMCONSOLE_MTP_ACCEPT_BASELINE`` 等），
    此时 ``source`` 变为 ``manual``。
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from pathlib import Path

from ..config import Settings
from ..models import BaselineMetric, BaselineState

log = logging.getLogger("llmconsole.baseline")


class _Metric:
    """单项指标的采样与冻结。"""

    def __init__(self, name: str, manual: float | None, required: int, quantile: float):
        self.name = name
        self.manual = manual
        self.required = required
        self.quantile = quantile
        self.samples: list[float] = []
        self.value: float | None = None
        self.frozen = False

    def observe(self, v: float | None) -> None:
        if self.frozen or self.manual is not None:
            return
        if v is None or v <= 0:
            return
        self.samples.append(float(v))
        if len(self.samples) >= self.required:
            self.freeze()

    def freeze(self) -> None:
        if not self.samples:
            return
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, max(0, int(round(self.quantile * (len(ordered) - 1)))))
        self.value = round(ordered[idx], 4)
        self.frozen = True
        log.info("baseline %s frozen: %.4f (from %d samples)", self.name, self.value, len(ordered))

    @property
    def effective(self) -> float | None:
        return self.manual if self.manual is not None else self.value

    def to_model(self) -> BaselineMetric:
        if self.manual is not None:
            return BaselineMetric(
                state="ready",
                samples=len(self.samples),
                required=self.required,
                value=self.manual,
                source="manual",
            )
        if self.frozen and self.value is not None:
            return BaselineMetric(
                state="ready",
                samples=len(self.samples),
                required=self.required,
                value=self.value,
                source="learned",
            )
        return BaselineMetric(
            state="learning", samples=len(self.samples), required=self.required, value=None, source="none"
        )

    def dump(self) -> dict:
        return {"samples": self.samples, "value": self.value, "frozen": self.frozen}

    def load(self, d: dict) -> None:
        self.samples = [float(x) for x in (d.get("samples") or [])]
        v = d.get("value")
        self.value = float(v) if v is not None else None
        self.frozen = bool(d.get("frozen")) and self.value is not None


class BaselineLearner:
    """MTP 接受率 + 解码吞吐的自动基线。"""

    def __init__(self, settings: Settings, started_at: float | None = None):
        self.s = settings
        self.started_at = started_at if started_at is not None else time.monotonic()
        self.mtp = _Metric(
            "mtp_accept",
            settings.mtp_accept_baseline,
            settings.baseline_min_samples,
            settings.baseline_quantile,
        )
        self.decode = _Metric(
            "decode_tps",
            settings.decode_baseline_tps,
            settings.baseline_min_samples,
            settings.baseline_quantile,
        )
        self._load()

    # ------------------------------------------------------------------
    @property
    def warmed_up(self) -> bool:
        return (time.monotonic() - self.started_at) >= self.s.baseline_warmup_s

    def observe(self, mtp: float | None, decode: float | None) -> None:
        """每个采集节拍调用一次。学习期内的样本一律丢弃。"""
        if not self.warmed_up:
            return
        before = (self.mtp.frozen, self.decode.frozen)
        self.mtp.observe(mtp)
        self.decode.observe(decode)
        if (self.mtp.frozen, self.decode.frozen) != before:
            self._save()

    @property
    def mtp_baseline(self) -> float | None:
        return self.mtp.effective

    @property
    def decode_baseline(self) -> float | None:
        return self.decode.effective

    def state(self) -> BaselineState:
        return BaselineState(mtp=self.mtp.to_model(), decode=self.decode.to_model())

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self.s.baseline_relearn:
            return
        path = Path(self.s.baseline_path)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        try:
            self.mtp.load(d.get("mtp") or {})
            self.decode.load(d.get("decode") or {})
            if self.mtp.frozen or self.decode.frozen:
                log.info(
                    "baseline restored from %s (mtp=%s decode=%s)", path, self.mtp.value, self.decode.value
                )
        except (TypeError, ValueError) as exc:
            log.warning("baseline file unreadable, relearning: %s", exc)

    def _save(self) -> None:
        path = Path(self.s.baseline_path)
        try:
            os.makedirs(path.parent, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"mtp": self.mtp.dump(), "decode": self.decode.dump()}, f, ensure_ascii=False, indent=2
                )
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("baseline persist failed: %s", exc)

    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """供日志/测试报告使用。"""
        st = self.state()
        return {
            "warmed_up": self.warmed_up,
            "mtp": st.mtp.model_dump(),
            "decode": st.decode.model_dump(),
            "quantile": self.s.baseline_quantile,
            "median_of_samples": (statistics.median(self.mtp.samples) if self.mtp.samples else None),
        }
