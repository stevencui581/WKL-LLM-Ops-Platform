"""采集器基类：超时、重试与陈旧标记（方案 6.1.5 / TASK-13）。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


@dataclass
class CollectorState:
    name: str
    stale_after: int = 3
    misses: int = 0
    last_ok_ts: float = 0.0
    last_error: str | None = None
    samples: int = 0
    errors: int = 0
    avg_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def ok(self, dur_ms: float = 0.0) -> None:
        self.misses = 0
        self.last_ok_ts = time.time()
        self.last_error = None
        self.samples += 1
        self.avg_ms = dur_ms if self.samples == 1 else self.avg_ms * 0.7 + dur_ms * 0.3

    def fail(self, err: str) -> None:
        self.misses += 1
        self.last_error = err
        self.errors += 1

    def reset(self) -> None:
        """清空失败状态（不改变累计 samples/errors 统计）。

        用于**非故障**的可用性切换：例如换了推理框架后某个接口不再存在，
        此时不应继续累计 misses —— 否则界面上会一直显示"降级"，
        而那其实只是"该框架没这个接口"。
        """
        self.misses = 0
        self.last_error = None

    @property
    def stale(self) -> bool:
        return self.misses >= self.stale_after

    @property
    def age_s(self) -> float | None:
        return None if not self.last_ok_ts else time.time() - self.last_ok_ts

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "stale": self.stale,
            "misses": self.misses,
            "last_ok_ts": self.last_ok_ts or None,
            "age_s": round(self.age_s, 1) if self.age_s is not None else None,
            "last_error": self.last_error,
            "samples": self.samples,
            "errors": self.errors,
            "avg_ms": round(self.avg_ms, 1),
        }


def to_num(v: Any) -> float | None:
    """nvidia-smi 的 ``[N/A]``/``[Not Supported]`` 一律转 None，**绝不转成 0**。

    方案 TASK-06 实现要点 6：把 N/A 当成 0 会产生假的低功耗/零温度告警。
    同时容忍带单位的数值（如 ``14590 MiB``、``39.55 W``）。
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.startswith("[") or s.lower() in ("n/a", "nan", "none", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        m = NUM_RE.match(s)
        return float(m.group(1)) if m else None


def to_int(v: Any) -> int | None:
    f = to_num(v)
    return None if f is None else int(f)
