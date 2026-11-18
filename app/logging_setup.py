"""日志初始化（方案 TASK-21 / 12.7 第 20 条）。

输出到 stdout 交给 journald。**Formatter 不输出时间戳、PID、主机名，也不输出
ANSI 颜色码** —— journald 会自动补齐元数据，重复输出会污染 grep 与 jq。
"""

from __future__ import annotations

import logging
import os
import sys

FORMAT = "%(levelname)s [%(name)s] %(message)s"


class JournaldFormatter(logging.Formatter):
    """只保留级别与消息主体，不重复 journald 已有的字段。"""

    def format(self, record: logging.LogRecord) -> str:
        record.name = record.name.replace("llmconsole.", "")
        return super().format(record)


def setup_logging(level: str | None = None) -> logging.Logger:
    """初始化日志。

    ``level`` 由调用方传入（``main.py`` 传 ``Settings.log_level``）；
    未传入时回退到 ``LLMCONSOLE_LOG_LEVEL`` 环境变量 —— 这样在**加载 Settings
    之前**就要打日志的场景（脚本、探针）也能工作。
    """
    lvl = (level or os.environ.get("LLMCONSOLE_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JournaldFormatter(FORMAT))
    root = logging.getLogger("llmconsole")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, lvl, logging.INFO))
    root.propagate = False

    # uvicorn 的访问日志另行控制（--no-access-log），此处只统一级别
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.propagate = False
    return root
