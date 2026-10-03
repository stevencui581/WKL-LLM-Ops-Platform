"""Markdown → DOCX 的**纯文本处理**（无第三方依赖）。

为什么单独拆出来：
    ``md2docx.py`` 需要 ``python-docx``，而 目标服务器上并没有装它
    （文档生成是开发机侧的工作）。于是这些**纯字符串逻辑**在服务器上
    无法被测试覆盖 —— 而「文档生成器给中文插零宽空格」这个缺陷恰恰
    就藏在这里。

    把 ``ZWSP`` / ``brk`` / ``plain`` / ``disp_len`` 抽到本模块后：
      * 不依赖 python-docx，服务器与开发机都能直接导入并测试；
      * 缺陷有了可重复执行的守卫（``tests/test_defect_ledger.py`` D8）。

**关键修复（D8）**：``brk()`` 原本对**每个**斜杠都插零宽空格，
于是「中/英切换」这类中文词也被插入了不可见字符，导致
    ① 从 DOCX 复制出来的文本失真；
    ② ``--contains`` 之类的文本断言失配。
现在只在 **ASCII token 内部**的斜杠处插入 —— 长路径仍需断行，
中文不再受影响（中文本来就能任意字符换行）。
"""

from __future__ import annotations

import re

#: 零宽空格：给长 ASCII token 提供换行机会，视觉上不可见
ZWSP = "\u200b"

#: ASCII token 里允许出现的字符（路径、命令、版本号、包名等）
_ASCII_TOKEN = r"[0-9A-Za-z._~%+@-]"

#: 仅当斜杠**两侧都是 ASCII token 字符**时才插断点
_BRK_RE = re.compile(rf"(?<={_ASCII_TOKEN})/(?={_ASCII_TOKEN})")


def brk(text: str) -> str:
    """给长 ASCII 路径/斜杠串插入零宽断点，避免窄单元格里被裁切。

    LibreOffice/Word 在 ``/`` 处通常不换行，像
    ``/usr/include/x86_64-linux-gnu/cudnn_version.h`` 这种长 token
    会把单元格撑破、渲染到页边距之外。

    **只在 ASCII token 内部插入**：中文本来就可以任意字符断行，
    而且给「中/英切换」这类词插零宽空格会让文档文本检索失真。
    """
    return _BRK_RE.sub("/" + ZWSP, text)


def plain(text: str) -> str:
    """去掉 markdown 标记与零宽空格，用于宽度估算。"""
    t = text.replace(ZWSP, "")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", t)
    return t


def disp_len(s: str) -> int:
    """显示宽度：CJK 字符按 2 计，其它按 1 计。"""
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0x2E7F else 1
    return n
