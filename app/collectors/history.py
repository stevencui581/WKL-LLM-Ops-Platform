"""历史服务日志查询（TASK-52 / v0.4.3 §3）。

需求：历史服务日志页要能按 **1 / 7 / 30 天**查看并下载，每条带完整日期时间。

设计取舍（方案 §2.1 已实测论证）：
  * **按需查询 journald**，控制台不再自建一份 —— 目标 上 journald 保留约 4 个月、
    30 天仅 10,309 行 / 1.2 秒，直接查是最合理且不重复占磁盘的做法；
  * 复用 ``logregex`` 的解析，字段语义与主页日志面板一致；
  * 结果**按天缓存 TTL 秒**，避免频繁点档位反复起进程；
  * 查询失败/超时**明确降级**为 ``available=false`` + 原因，页面显示提示而非空白；
  * 实际覆盖区间由首末行的真实时间戳计算并**如实上报** ——
    若某台机器 journald 保留不足 30 天，页面会显示真实天数，而不是谎称 30 天。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..models import LogLine
from .journal import parse_journal_line

log = logging.getLogger(__name__)


@dataclass
class HistoryResult:
    lines: list[LogLine] = field(default_factory=list)
    requested_days: int = 30
    covered_from: str = ""
    covered_to: str = ""
    covered_days: float = 0.0
    total_in_range: int = 0
    returned: int = 0
    truncated: bool = False
    available: bool = True
    error: str = ""
    source: str = "journald"
    elapsed_ms: float = 0.0


#: journalctl 的**分隔行**形态。
#:
#: ``short-iso`` 输出在查询范围跨重启时会插入::
#:
#:     -- Boot c62e718a0de6467e9ab147ad01b90086 --
#:     -- Reboot --
#:
#: 这些行没有时间戳与日志级别，属于**结构标记**而非日志内容。
_SEPARATOR_RE = re.compile(r"^--\s+\S.*\s+--$")


def _is_separator(text: str) -> bool:
    """判断是否 journalctl 的结构分隔行。"""
    t = (text or "").strip()
    return bool(_SEPARATOR_RE.match(t)) and len(t) < 200


class LogHistory:
    """按时间范围查询 journald（带 TTL 缓存）。"""

    def __init__(self, settings: Settings):
        self.s = settings
        #: 缓存键必须是 ``(days, limit)`` —— 只按 days 缓存会导致
        #: "先查 2000 行、再查全量"命中旧结果（实测踩过的坑）
        self._cache: dict[tuple[int, int], tuple[float, HistoryResult]] = {}
        self.query_count = 0
        self.error_count = 0

    # ------------------------------------------------------------------ 参数
    def resolve_days(self, days: int | None) -> int:
        """把请求的档位收敛到配置允许的集合；非法值回退默认档。"""
        allowed = tuple(self.s.log_history_days_options)
        if days is None:
            return int(self.s.log_history_default_days)
        try:
            d = int(days)
        except (TypeError, ValueError):
            return int(self.s.log_history_default_days)
        if d in allowed:
            return d
        # 取不超过请求值的最接近档位；都比请求大则取最小档
        lower = [a for a in allowed if a <= d]
        return int(max(lower)) if lower else int(min(allowed))

    def build_argv(self, days: int, limit: int) -> list[str]:
        """构造查询命令。

        用 ``--since "-Nd"`` 而不是 ``-n``：天数才是需求单位。
        同时给 ``-n limit+1`` 作为硬上限（多取一行用于判断是否被截断）。
        """
        return [
            self.s.journalctl,
            "-u",
            self.s.llama_unit,
            "--since",
            f"-{days}d",
            "-n",
            str(limit + 1),
            "--no-pager",
            "-o",
            "short-iso",
        ]

    # ------------------------------------------------------------------ 查询
    def cached(self, days: int, limit: int) -> HistoryResult | None:
        got = self._cache.get((days, limit))
        if got is None:
            return None
        at, res = got
        if time.monotonic() - at > self.s.log_history_ttl_s:
            return None
        return res

    def invalidate(self) -> None:
        self._cache.clear()

    async def fetch(
        self, days: int | None = None, limit: int | None = None, force: bool = False
    ) -> HistoryResult:
        d = self.resolve_days(days)
        lim = int(limit or self.s.log_history_default_limit)
        lim = max(1, min(lim, int(self.s.log_history_max_lines)))
        if not force:
            hit = self.cached(d, lim)
            if hit is not None:
                return hit
        res = await self._run_query(d, lim)
        self._cache[(d, lim)] = (time.monotonic(), res)
        self._evict()
        return res

    def _evict(self) -> None:
        """限制缓存条目数。

        每条结果最多可含 15,000 行日志（约 10 MB Python 对象），
        若不限制，不同 (days, limit) 组合会让常驻内存无界增长。
        保留最近使用的 4 条足够覆盖 1/7/30 天三档 + 一次自定义 limit。
        """
        max_entries = 4
        if len(self._cache) <= max_entries:
            return
        oldest = sorted(self._cache.items(), key=lambda kv: kv[1][0])
        for key, _ in oldest[: len(self._cache) - max_entries]:
            self._cache.pop(key, None)

    async def _run_query(self, days: int, limit: int) -> HistoryResult:
        argv = self.build_argv(days, limit)
        res = HistoryResult(requested_days=days)
        t0 = time.monotonic()
        self.query_count += 1
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.s.stream_reader_limit,
            )
            async with asyncio.timeout(self.s.log_history_timeout_s):
                out_b, err_b = await proc.communicate()
        except TimeoutError:
            self.error_count += 1
            res.available = False
            res.error = f"查询超时（>{self.s.log_history_timeout_s:.0f}s）"
            res.elapsed_ms = (time.monotonic() - t0) * 1000
            log.warning("log history timeout: days=%d", days)
            return res
        except (FileNotFoundError, OSError) as exc:
            self.error_count += 1
            res.available = False
            res.error = f"journalctl 不可用：{exc}"
            res.elapsed_ms = (time.monotonic() - t0) * 1000
            return res

        if proc.returncode not in (0, None):
            self.error_count += 1
            res.available = False
            res.error = (err_b.decode("utf-8", "replace").strip().splitlines() or ["查询失败"])[-1]
            res.elapsed_ms = (time.monotonic() - t0) * 1000
            return res

        raw_lines = [ln for ln in out_b.decode("utf-8", "replace").splitlines() if ln.strip()]
        res.total_in_range = len(raw_lines)
        res.truncated = len(raw_lines) > limit
        picked = raw_lines[-limit:] if res.truncated else raw_lines
        parsed = [parse_journal_line(ln) for ln in picked]
        parsed = [p for p in parsed if p.text or p.ts]
        # journalctl 在范围跨重启时会插入无时间戳的分隔行（如 `-- Boot xxx --`）。
        # 显式标注为 separator，前端渲染为分隔条而不是一行空白时间戳。
        for p in parsed:
            if not p.ts and _is_separator(p.text):
                p.kind = "separator"
        # 最新在前
        parsed.reverse()
        res.lines = parsed
        res.returned = len(parsed)
        if parsed:
            times = [p.epoch for p in parsed if p.epoch]
            if times:
                lo, hi = min(times), max(times)
                res.covered_from = _fmt(lo)
                res.covered_to = _fmt(hi)
                res.covered_days = round((hi - lo) / 86400.0, 2)
            # 若解析不出 epoch，退化为用文本首末行展示
            if not res.covered_from:
                res.covered_from = parsed[-1].ts
                res.covered_to = parsed[0].ts
        res.elapsed_ms = (time.monotonic() - t0) * 1000
        return res

    # ------------------------------------------------------------------ 导出
    async def export_text(self, days: int | None = None) -> tuple[str, str, int, str]:
        """导出当前范围的日志文本。

        返回 ``(文件名, 正文, 行数, 错误)``。正文按**时间正序**（从旧到新），
        与 ``journalctl`` 原始顺序一致，便于人读与归档。
        """
        d = self.resolve_days(days)
        lim = int(self.s.log_history_max_lines)
        res = await self.fetch(d, limit=lim, force=True)
        if not res.available:
            return "", "", 0, res.error
        rows = list(reversed(res.lines))  # 回到时间正序
        stamp = time.strftime("%Y%m%d-%H%M")
        fname = f"{self.s.llama_unit}_{d}d_{stamp}.log"
        header = (
            f"# {self.s.product_name}\n"
            f"# unit: {self.s.llama_unit}\n"
            f"# range: last {d} day(s)\n"
            f"# covered: {res.covered_from} ~ {res.covered_to} "
            f"({res.covered_days} day(s))\n"
            f"# lines: {len(rows)}\n"
            f"# exported: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'#' * 72}\n"
        )
        body = header + "".join(f"{r.ts}  {r.level}  {r.text}\n" for r in rows)
        return fname, body, len(rows), ""

    def stats(self) -> dict:
        return {
            "queries": self.query_count,
            "errors": self.error_count,
            "cached_keys": sorted([f"{d}d/{n}" for d, n in self._cache]),
        }


def _fmt(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
