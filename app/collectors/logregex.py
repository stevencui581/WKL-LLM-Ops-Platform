"""llama.cpp 日志解析（方案 4.3 / 附录 B）。

设计要点（V4.1 TASK-08）：
  * 解析函数 **永不抛异常** —— 跟随循环里未捕获异常会终止采集；
  * 时间戳一律取 journald 的壁钟时间，**绝不**使用 llama.cpp 行内的运行时长度
    （``2990.36.159.181`` 是「运行分钟.秒.毫秒.微秒」，不是 IP 也不是时间）；
  * 每个线上解析缺陷都要沉淀成 tests/fixtures 里的用例。
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import LogLine

# --------------------------------------------------------------------------
# 日志级别与高亮
# --------------------------------------------------------------------------
RE_LEVEL = re.compile(r"^\S+\s+([IWED])\s")

HIGHLIGHT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("exit", re.compile(r"exited with status|exit command received", re.I)),
    ("oom", re.compile(r"\boom\b|out of memory|cuda error", re.I)),
    ("cancel", re.compile(r"cancel task", re.I)),
    ("truncated", re.compile(r"truncated\s*=\s*1")),
    ("loaded", re.compile(r"model loaded")),
    ("error", re.compile(r"\berror\b|failed", re.I)),
]

# --------------------------------------------------------------------------
# 结构化字段
# --------------------------------------------------------------------------
RE_ACCEPT = re.compile(
    r"draft acceptance\s*=\s*([\d.]+)\s*\(\s*(\d+)\s+accepted\s*/\s*(\d+)\s+generated\s*\)"
    r"\s*,\s*mean len\s*=\s*([\d.]+)"
)
RE_EVAL = re.compile(
    # 必须排除「prompt eval time」——否则会与 RE_PREFILL 重叠，
    # 导致「最近请求明细」里的生成速率被填成预填充速率。
    r"(?<!prompt )eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens\s*"
    r"\(\s*([\d.]+)\s*ms per token\s*,\s*([\d.]+)\s*tokens per second\s*\)"
)
RE_PREFILL = re.compile(
    r"prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens\s*"
    r"\(\s*([\d.]+)\s*ms per token\s*,\s*([\d.]+)\s*tokens per second\s*\)"
)
RE_PROGRESS = re.compile(
    r"n_gen\s*=\s*(\d+)\s*,\s*tg\s*=\s*([\d.]+)\s*t/s"
    r"\s*,\s*tg_3s\s*=\s*([\d.]+)\s*t/s"
)
RE_SLOT = re.compile(r"slot\s+\w+\s*:\s*id\s*(\d+)\s*\|\s*task\s*(-?\d+)")
RE_RELEASE = re.compile(r"stop processing:\s*n_tokens\s*=\s*(\d+)\s*,\s*truncated\s*=\s*(\d+)")
RE_LCP = re.compile(r"f_sim_best\s*=\s*([\d.]+).*?f_keep\s*=\s*([\d.]+)")
RE_EXIT = re.compile(r"exited with status\s*(\d+)")
RE_LOADED = re.compile(r"llama_server:\s*model loaded")
RE_TOTAL_TIME = re.compile(r"total time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens")
RE_GRAPHS = re.compile(r"graphs reused\s*=\s*(\d+)")

# journalctl -o short-iso 行前缀：  2026-10-01T17:19:24+06:00 llm-host llama-server[1261]: msg
RE_JOURNAL_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z))"
    r"\s+(?P<host>\S+)\s+(?P<ident>[^:]+):\s?(?P<msg>.*)$"
)


def parse_journal_line(raw: str) -> LogLine:
    """把一行 journalctl 输出解析为 LogLine。永不抛异常。"""
    line = LogLine(text=raw.rstrip("\n"))
    if not raw.strip():
        return line

    m = RE_JOURNAL_PREFIX.match(raw)
    body = raw
    if m:
        line.ts = m.group("ts")
        body = m.group("msg")
        try:
            line.epoch = datetime.fromisoformat(m.group("ts")).timestamp()
        except ValueError:
            line.epoch = 0.0
    line.text = body.strip()

    lv = RE_LEVEL.match(line.text) or RE_LEVEL.match(body)
    if lv:
        line.level = lv.group(1)

    sl = RE_SLOT.search(body)
    if sl:
        line.slot = int(sl.group(1))
        line.task = int(sl.group(2))

    for name, pat in HIGHLIGHT_PATTERNS:
        if pat.search(body):
            line.highlight = name
            break
    return line


def parse_acceptance(text: str) -> dict | None:
    m = RE_ACCEPT.search(text)
    if not m:
        return None
    gen = int(m.group(3))
    acc = int(m.group(2))
    return {
        "rate": float(m.group(1)),
        "accepted": acc,
        "generated": gen,
        "mean_len": float(m.group(4)),
        "ratio": (acc / gen) if gen else None,
    }


def parse_eval(text: str) -> dict | None:
    m = RE_EVAL.search(text)
    if not m:
        return None
    return {
        "ms": float(m.group(1)),
        "tokens": int(m.group(2)),
        "ms_per_token": float(m.group(3)),
        "tps": float(m.group(4)),
    }


def parse_prefill(text: str) -> dict | None:
    m = RE_PREFILL.search(text)
    if not m:
        return None
    return {
        "ms": float(m.group(1)),
        "tokens": int(m.group(2)),
        "ms_per_token": float(m.group(3)),
        "tps": float(m.group(4)),
    }


def parse_progress(text: str) -> dict | None:
    m = RE_PROGRESS.search(text)
    if not m:
        return None
    return {"n_gen": int(m.group(1)), "tg": float(m.group(2)), "tg_3s": float(m.group(3))}


def parse_release(text: str) -> dict | None:
    m = RE_RELEASE.search(text)
    if not m:
        return None
    return {"n_tokens": int(m.group(1)), "truncated": int(m.group(2))}


def parse_lcp(text: str) -> dict | None:
    m = RE_LCP.search(text)
    if not m:
        return None
    return {"f_sim_best": float(m.group(1)), "f_keep": float(m.group(2))}


def parse_total_time(text: str) -> dict | None:
    m = RE_TOTAL_TIME.search(text)
    if not m:
        return None
    return {"ms": float(m.group(1)), "tokens": int(m.group(2))}


def parse_exit(text: str) -> dict | None:
    m = RE_EXIT.search(text)
    if not m:
        return None
    return {"status": int(m.group(1))}


def parse_all(text: str) -> dict:
    """一次抽取全部可识别字段，返回非空项。"""
    out: dict = {}
    for key, fn in (
        ("acceptance", parse_acceptance),
        ("eval", parse_eval),
        ("prefill", parse_prefill),
        ("progress", parse_progress),
        ("release", parse_release),
        ("lcp", parse_lcp),
        ("total_time", parse_total_time),
        ("exit", parse_exit),
    ):
        v = fn(text)
        if v is not None:
            out[key] = v
    if RE_LOADED.search(text):
        out["model_loaded"] = True
    return out
