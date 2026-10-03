"""历史日志行的类型标注（v0.5.1 回归）。

**真实发现**

    ``journalctl -o short-iso`` 在查询范围**跨重启**时会插入结构分隔行::

        -- Boot c62e718a0de6467e9ab147ad01b90086 --
        -- Reboot --

    它们**没有时间戳**。早期版本把它们当普通日志行返回，后果是：

      * 前端渲染出一行空白时间戳，看起来像数据损坏
      * 验收探针里 ``all(len(ts_local) == 19)`` 的断言失败 ——
        而且**只在机器恰好于查询范围内重启过时才失败**，属于间歇性误报

    现在这些行会被显式标注 ``kind="separator"``，让前端能正确渲染为分隔条。
"""

from __future__ import annotations

from app.collectors.history import _is_separator
from app.models import LogLine


# ===========================================================================
# 1. 分隔行识别
# ===========================================================================
def test_boot_separator_recognised():
    assert _is_separator("-- Boot c62e718a0de6467e9ab147ad01b90086 --")
    assert _is_separator("-- Reboot --")
    assert _is_separator("  -- Boot abc123 --  ")  # 容忍空白


def test_normal_log_lines_are_not_separators():
    """普通日志行不能被误判为分隔行。"""
    for text in (
        "2026-10-03T23:23:03+06:00 llm-host llama-server[1261]: model loaded",
        "srv  update_slots: all slots are idle",
        "-- something without closing dashes",
        "a -- b -- c",  # 中间有短横但不以 -- 开头
        "",
    ):
        assert not _is_separator(text), f"误判为分隔行：{text!r}"


def test_long_line_is_not_separator():
    """超长行即使形态相似也不算分隔行（防止把日志正文误判）。"""
    assert not _is_separator("-- " + "x" * 300 + " --")


# ===========================================================================
# 2. 模型字段
# ===========================================================================
def test_logline_has_kind_field():
    """LogLine 必须有 kind 字段，默认值为 log。"""
    line = LogLine(text="hello")
    assert line.kind == "log", "默认 kind 应为 log"
    assert "kind" in LogLine.model_fields


def test_separator_line_has_empty_timestamp():
    """分隔行没有时间戳 —— 这是它与日志行的本质区别。"""
    sep = LogLine(text="-- Boot abc --", kind="separator")
    assert sep.ts == ""
    assert sep.epoch == 0.0


def test_kind_survives_serialisation():
    """kind 必须随 model_dump 下发到前端。"""
    sep = LogLine(text="-- Reboot --", kind="separator")
    assert sep.model_dump()["kind"] == "separator"


# ===========================================================================
# 3. 契约：日志行必须有完整时间戳，分隔行必须被标注
# ===========================================================================
def test_contract_for_history_lines():
    """模拟一次返回：日志行 + 一条分隔行。

    这是验收探针断言的**真实契约** —— 而不是"每一行都必须有 19 字符时间戳"。
    """
    lines = [
        LogLine(ts="2026-10-03 23:23:03", epoch=1790000000.0, text="model loaded"),
        LogLine(ts="", epoch=0.0, text="-- Boot c62e718a0de6467e9ab147ad01b90086 --", kind="separator"),
        LogLine(ts="2026-10-03 23:23:04", epoch=1790000001.0, text="slot released"),
    ]
    logs = [x for x in lines if x.kind == "log"]
    seps = [x for x in lines if x.kind == "separator"]
    assert all(len(x.ts) == 19 for x in logs), "日志行必须有完整时间戳"
    assert all(x.ts == "" for x in seps), "分隔行不应有伪造的时间戳"
    assert len(seps) == 1
