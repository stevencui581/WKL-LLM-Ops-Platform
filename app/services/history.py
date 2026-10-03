"""历史环形缓冲（方案 TASK-10 / 6.2.4）。

容量 150 点 = 2 秒 × 5 分钟；内存占用约 300 KB（实测需 < 1 MB）。
"""

from __future__ import annotations

import time
from collections import deque

from ..config import Settings
from ..models import MetricSnapshot

SERIES = (
    "decode_tps",
    "prefill_tps",
    "mtp_accept",
    "kv_pct",
    "vram_pct",
    "gpu0_temp",
    "gpu1_temp",
    "gpu0_power",
    "gpu1_power",
    "processing",
)


class History:
    def __init__(self, settings: Settings):
        self.s = settings
        self.points: deque[dict] = deque(maxlen=settings.history_points)

    def add(self, snap: MetricSnapshot) -> None:
        gpus = {g.index: g for g in snap.gpus}
        vram_pct = None
        if snap.kpi.vram_used_mib and snap.kpi.vram_total_mib:
            vram_pct = snap.kpi.vram_used_mib / snap.kpi.vram_total_mib * 100.0

        def gv(i: int, attr: str) -> float | None:
            g = gpus.get(i)
            return getattr(g, attr, None) if g else None

        self.points.append(
            {
                "ts": snap.ts,
                "decode_tps": snap.kpi.decode_tps,
                "prefill_tps": snap.kpi.prefill_tps,
                "mtp_accept": snap.kpi.mtp_accept,
                "kv_pct": snap.kv.pct,
                "vram_pct": vram_pct,
                "gpu0_temp": gv(0, "temp_c"),
                "gpu1_temp": gv(1, "temp_c"),
                "gpu0_power": gv(0, "power_w"),
                "gpu1_power": gv(1, "power_w"),
                "processing": snap.kpi.processing,
            }
        )

    def window(self, seconds: float) -> list[dict]:
        cutoff = time.time() - seconds
        return [p for p in self.points if p["ts"] >= cutoff]

    def as_dict(self) -> dict:
        return {"points": list(self.points), "series": list(SERIES)}

    def bytes_estimate(self) -> int:
        """粗略内存占用估算，用于 TASK-10 的 <1 MB 断言。"""
        import sys

        if not self.points:
            return 0
        sample = self.points[-1]
        per = sys.getsizeof(sample) + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in sample.items())
        return per * len(self.points)
