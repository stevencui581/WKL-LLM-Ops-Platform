"""告警日志记录器（TASK-50 / v0.4.3 §6.1）。

记录每一次告警的**产生（raised）**与**恢复（resolved）**，供独立页面查询。

设计：
  * 内存环形缓冲（默认 2000 条），页面默认取最近 500 条；
  * 追加落盘 ``state/alert_log.jsonl``，**重启不丢**；
  * 文件超过阈值时重写为最近 N 条，避免无限增长；
  * 同一个 code 持续存在期间**只记一条 raised**（与告警引擎的去抖语义一致），
    恢复时记一条 resolved —— 因此日志天然被"抑制"过，不会刷屏；
  * 写入失败只记 debug 日志，**不影响采集主流程**。
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import alert_catalog

log = logging.getLogger(__name__)

RAISED = "raised"
RESOLVED = "resolved"


def _iso(ts: float) -> str:
    """本地时区的 ``YYYY-MM-DD HH:MM:SS``（页面直接展示，不做二次格式化）。"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(slots=True)
class AlertLogEntry:
    """一条告警日志。

    ``category`` / ``name`` 同时给出中英两种（前端按语言选），
    这样后端不需要知道"当前是什么语言" —— 语言属于展示层。
    """

    seq: int
    ts: float
    iso: str
    code: str
    level: str
    event: str  # raised | resolved
    category_zh: str
    category_en: str
    name_zh: str
    name_en: str
    message: str = ""
    value: float | None = None
    service: str = ""
    duration_s: float | None = None  # 仅 resolved：本次告警持续时长

    def to_dict(self) -> dict:
        return asdict(self)

    def as_public(self) -> dict:
        """对外形态：分类/名称按语言组织，避免前端再拼。"""
        d = self.to_dict()
        d["category"] = {"zh": d.pop("category_zh"), "en": d.pop("category_en")}
        d["name"] = {"zh": d.pop("name_zh"), "en": d.pop("name_en")}
        return d


@dataclass
class AlertLog:
    """告警日志（内存环形 + 落盘）。"""

    path: Path
    ring_max: int = 2000
    file_max: int = 10000
    service: str = ""
    entries: deque[AlertLogEntry] = field(default_factory=deque)
    _seq: int = 0
    _since: dict[str, float] = field(default_factory=dict)  # code -> 产生时刻
    _append_failures: int = 0

    def __post_init__(self) -> None:
        # 容忍传入 str（配置里就是字符串），统一成 Path
        if not isinstance(self.path, Path):
            self.path = Path(self.path)

    # ------------------------------------------------------------------ 记录
    def record(
        self,
        code: str,
        level: str,
        event: str,
        message: str = "",
        value: float | None = None,
        now: float | None = None,
    ) -> AlertLogEntry:
        now = time.time() if now is None else now
        m = alert_catalog.meta(code)
        duration: float | None = None
        if event == RAISED:
            self._since.setdefault(code, now)
        elif event == RESOLVED:
            started = self._since.pop(code, None)
            if started is not None:
                duration = round(now - started, 1)
        self._seq += 1
        entry = AlertLogEntry(
            seq=self._seq,
            ts=now,
            iso=_iso(now),
            code=code,
            level=level,
            event=event,
            category_zh=m.category_zh,
            category_en=m.category_en,
            name_zh=m.name_zh,
            name_en=m.name_en,
            message=message,
            value=value,
            service=self.service,
            duration_s=duration,
        )
        self.entries.append(entry)
        while len(self.entries) > self.ring_max:
            self.entries.popleft()
        self._append(entry)
        return entry

    def sync(self, active: Mapping[str, object], now: float | None = None) -> list[AlertLogEntry]:
        """把告警引擎的 active 集合与日志对齐，返回本次新增的事件。

        调用点：``AlertEngine.evaluate()`` 每次评估后。
        """
        now = time.time() if now is None else now
        fresh: list[AlertLogEntry] = []
        seen = set(active)
        # 新出现的 → raised
        for code, alert in active.items():
            if code in self._since:
                continue
            fresh.append(
                self.record(
                    code,
                    getattr(alert, "level", "warning"),
                    RAISED,
                    getattr(alert, "message", ""),
                    getattr(alert, "value", None),
                    now,
                )
            )
        # 已消失的 → resolved
        for code in list(self._since):
            if code not in seen:
                fresh.append(self.record(code, "info", RESOLVED, "", None, now))
        return fresh

    # ------------------------------------------------------------------ 查询
    def recent(
        self, limit: int = 500, level: str | None = None, q: str | None = None, event: str | None = None
    ) -> list[AlertLogEntry]:
        items: list[AlertLogEntry] = list(self.entries)
        if event in (RAISED, RESOLVED):
            items = [e for e in items if e.event == event]
        if level:
            order = {"info": 0, "warning": 1, "critical": 2}
            want = order.get(level.lower(), 0)
            items = [e for e in items if order.get(e.level, 0) >= want]
        if q:
            needle = q.lower()
            items = [
                e
                for e in items
                if needle in e.message.lower()
                or needle in e.code.lower()
                or needle in e.name_en.lower()
                or needle in e.name_zh.lower()
            ]
        return items[-limit:][::-1]  # 最新在前

    @property
    def total(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------ 落盘
    def _append(self, entry: AlertLogEntry) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            self._append_failures += 1
            log.debug("alert log append failed: %s", exc)
            return
        # 文件过大时裁剪（低频：只在超过阈值时重写一次）
        try:
            if self.path.stat().st_size > 0 and self._line_count_hint() > self.file_max:
                self._compact()
        except OSError:
            pass

    def _line_count_hint(self) -> int:
        """行数上界估计：按平均行长估算，避免每次记录都读整个文件。"""
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        # 经验值：一条记录 JSON 约 380~450 字节
        return int(size / 400)

    def _compact(self) -> None:
        keep = list(self.entries)[-max(self.ring_max, 1000) :]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for e in keep:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(self.path)
            log.info("alert log compacted to %d entries", len(keep))
        except OSError as exc:
            log.debug("alert log compact failed: %s", exc)

    def load(self) -> int:
        """启动时读回最近 ``ring_max`` 条。返回读入条数。"""
        try:
            if not self.path.exists():
                return 0
            with open(self.path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-self.ring_max :]
        except OSError as exc:
            log.debug("alert log load failed: %s", exc)
            return 0
        n = 0
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
                entry = AlertLogEntry(**d)
            except (ValueError, TypeError):
                continue  # 坏行跳过，不影响其余
            self.entries.append(entry)
            self._seq = max(self._seq, entry.seq)
            if entry.event == RAISED:
                self._since.setdefault(entry.code, entry.ts)
            n += 1
        # 重建 _since 时，已 resolved 的要移除
        for e in self.entries:
            if e.event == RESOLVED:
                self._since.pop(e.code, None)
        log.info("alert log loaded %d entries", n)
        return n

    def stats(self) -> dict:
        counts = {RAISED: 0, RESOLVED: 0}
        for e in self.entries:
            counts[e.event] = counts.get(e.event, 0) + 1
        return {
            "total": len(self.entries),
            "by_event": counts,
            "ring_max": self.ring_max,
            "file_max": self.file_max,
            "append_failures": self._append_failures,
        }
