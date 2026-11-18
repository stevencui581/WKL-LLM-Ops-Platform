"""snapshot 必须携带前端所需字段（v0.5 回归）。

**真实缺陷**：顶栏「框架」徽标一直显示「识别中…」。

排查过程：
    * 后端 `/api/overview` 有 `framework`  ✅
    * index.html 有 `#fwChip`             ✅
    * app.js 有 `renderFrameworkChip`     ✅
    静态检查全部通过，但页面上就是不动。

**根因**：`framework` 只挂在 **REST 路由**上，而页面每 2 秒被 **WebSocket**
推送的 `snapshot.model_dump()` 覆盖一次。快照里没有这个字段，
于是 `o.framework` 变成 `undefined`，徽标退回占位文案并永久停在那里。

本文件守卫的是那条通用规则：**凡是前端要用的字段，都必须出现在快照里** ——
REST 与 WebSocket 走同一份数据，否则会被下一次推送悄悄抹掉。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models import MetricSnapshot

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

#: 前端渲染时读取、因此**必须**由快照（而非仅 REST 路由）提供的字段
SNAPSHOT_REQUIRED = (
    "framework",
    "accelerator_badge",
    "llama_uptime_s",
    "hardware_ts",
    "baseline",
    "thresholds",
)


def test_snapshot_has_framework_field():
    """快照模型必须有 framework 字段（v0.5 回归）。"""
    s = MetricSnapshot()
    assert hasattr(s, "framework"), (
        "MetricSnapshot 缺少 framework 字段 —— 页面每 2 秒被 WebSocket 覆盖后，"
        "顶栏「框架」徽标会退回「识别中…」"
    )
    assert isinstance(s.framework, dict)


def test_snapshot_defaults_do_not_break_render():
    """空快照的 framework 必须是空字典（而不是 None）——
    前端据此判断"尚未识别"，若为 None 会让 `fw.name` 取值抛异常。"""
    s = MetricSnapshot()
    assert s.framework == {}
    assert s.framework is not None


def test_all_frontend_fields_are_in_snapshot():
    """前端读取的字段必须都在快照模型上。"""
    missing = [f for f in SNAPSHOT_REQUIRED if f not in MetricSnapshot.model_fields]
    assert not missing, f"MetricSnapshot 缺少前端所需字段：{missing}"


def test_aggregator_populates_framework_in_snapshot():
    """聚合器构造快照时必须填入 framework（否则 REST 有、WS 没有）。"""
    src = (APP / "services" / "aggregator.py").read_text(encoding="utf-8")
    # 找到 MetricSnapshot(...) 构造块
    m = re.search(r"return MetricSnapshot\((.*?)\n        \)", src, re.S)
    assert m, "未找到 MetricSnapshot 构造块"
    block = m.group(1)
    assert "framework=" in block, "聚合器构造快照时未传 framework —— WebSocket 推送会缺这个字段"


def test_overview_route_uses_snapshot_not_aggregator_only():
    """REST 路由也必须从快照取字段，保证两条路径同源。

    v0.6.1：路由改成 ``snap.model_dump()``，比原先"逐个字段抄一遍"**更强** ——
    手工拼装正是 v0.5 框架徽标与 v0.6 阈值/健康度两次漂移的共同根因。
    """
    src = (APP / "routes" / "overview.py").read_text(encoding="utf-8")
    assert "snap.model_dump()" in src, (
        "overview 路由必须整体 dump 快照，而不是逐字段拼装 —— 拼装会让新增字段只在 REST 出现，WS 推送后消失"
    )
    assert "aggregator.framework_dict()" not in src, (
        "不应单独调 aggregator.framework_dict()，两条路径必须同源"
    )


def test_ws_broadcast_serializes_whole_snapshot():
    """WebSocket 广播的是整个快照，因此快照字段即推送内容。"""
    src = (APP / "ws.py").read_text(encoding="utf-8")
    assert "snapshot.model_dump()" in src, "WebSocket 应广播完整快照；若改成分字段拼装，新增字段容易漏"


def test_frontend_gates_on_framework_presence():
    """前端在 framework 缺失时必须优雅降级，而不是抛异常。"""
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    # renderFrameworkChip 必须先判断 fw 与 fw.id 是否存在
    m = re.search(r"function renderFrameworkChip\((.*?)\n\}", src, re.S)
    assert m, "未找到 renderFrameworkChip"
    body = m.group(1)
    assert "if (!fw || !fw.id)" in body, (
        "renderFrameworkChip 必须先判断 fw 是否为空，否则 WebSocket 覆盖时会抛异常"
    )


def test_i18n_lang_is_a_getter_not_a_snapshot():
    """`I18N.lang` 必须是取值器。

    **真实缺陷**：原先写成 `lang: LANG`，那是加载时的值拷贝；
    `setLang('en')` 改的是闭包变量，导出对象不知道。
    后果是切换语言后框架徽标仍按旧语言取名字。
    """
    src = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "Object.defineProperty(global.I18N, 'lang'" in src, (
        "I18N.lang 应使用取值器；写成值拷贝会导致切换语言后其它模块读到旧语言"
    )
    # 不应再出现值拷贝写法
    assert not re.search(r"^\s*lang:\s*LANG,", src, re.M), "I18N 导出里仍有 `lang: LANG` 值拷贝"
