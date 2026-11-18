"""REST / WebSocket 载荷一致性守卫（v0.6.1 回归）。

**本文件守的是同一个根因的第三次复发。**

时间线：

  * v0.5 —— 顶栏「框架」徽标永久停在「识别中…」。根因：``framework`` 只挂在
    ``/api/overview``，而页面每 2 秒被 **WebSocket** 的
    ``MetricSnapshot.model_dump()`` 覆盖。修法是给快照加 ``framework``
    （见 ``tests/test_snapshot_fields.py``）。
  * v0.6 —— **同一个根因，另外三个字段**：``branding`` / ``thresholds`` / ``health``
    仍只在路由里手工拼装。后果：
      - ``state.thresholds = o.thresholds || {}`` ⇒ 阈值被抹成空字典，
        前端退回硬编码 95/85/87/83（= v0.4 已修过的 F5 缺陷复发）；
      - ``o.health`` 变成 ``undefined`` ⇒ 降级横幅永不出现，**总状态永远显示 ok**；
      - ``renderBranding(undefined)`` 直接 return ⇒ 产品名/版号退回静态兜底。
    **注意：415 项测试全绿也没能拦住它** —— 因为 ``test_snapshot_fields.py``
    只断言字段**存在于模型上**，不断言**聚合器真的填了值**，也不断言
    REST 与 WS 是同一份载荷。

本文件补上那三条盲区：

1. ``test_snapshot_payload_has_every_overview_field`` —— 载荷键集合 ⊇ 契约；
2. ``test_frontend_reads_only_keys_the_payload_provides`` —— 前端读的每个 ``o.<key>``
   都真的会被下发（**直接复现 D7 的错误判据**）；
3. ``test_rest_and_ws_payload_are_identical`` —— 同一个快照在两条路径上
   dump 出的**键集合必须完全相等**，且关键字段**非空**（不是形状对、内容是空）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.models import MetricSnapshot
from app.payload import HEALTH_FIELDS, OVERVIEW_FIELDS
from app.ws import WebSocketHub

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"

#: ``renderOverview(o)`` 的形参名。前端读载荷一律写成 ``o.<key>``，
#: 因此可以用一条正则把"前端到底要什么"提取成机器可校验的清单。
_PAYLOAD_VAR = "o"

#: 只在前端内部使用的键（不是后端契约的一部分）。
_FRONTEND_LOCAL_KEYS = {"severity"}


def _frontend_payload_keys() -> set[str]:
    """从 ``app.js`` 提取形如 ``o.<key>`` 的读取，返回去重后的键集合。"""
    src = APP_JS.read_text(encoding="utf-8")
    keys = set(re.findall(rf"\b{_PAYLOAD_VAR}\.([A-Za-z_][A-Za-z0-9_]*)", src))
    return keys - _FRONTEND_LOCAL_KEYS


def test_contract_lists_every_field_the_frontend_reads():
    """``OVERVIEW_FIELDS`` 契约必须覆盖前端读取的每一个字段。

    **这是本文件最重要的一条**：它把"前端读什么"与"后端承诺给什么"
    变成机器可校验的关系。新增一个 ``o.foo`` 却忘了加进契约 ⇒ 立刻失败。
    """
    frontend = _frontend_payload_keys()
    missing = sorted(frontend - set(OVERVIEW_FIELDS))
    assert not missing, (
        f"前端读取了载荷里没有承诺的字段：{missing}。"
        "若这些字段确实要下发，请加进 app/payload.py::OVERVIEW_FIELDS 并随快照下发。"
    )


def test_frontend_reads_only_keys_the_payload_provides():
    """直接复现 D7 的错误判据：前端读的键必须真的会被下发。

    这条测试在修复前**必失败** —— ``branding`` / ``thresholds`` / ``health``
    当时不在 ``metric_snapshot_payload()`` 的结果里。
    """
    payload_keys = set(metric_snapshot_payload())
    frontend = _frontend_payload_keys()
    missing = sorted(frontend - payload_keys)
    assert not missing, (
        f"前端读取的字段在快照载荷里不存在：{missing} —— 页面每 2 秒被 WS 覆盖一次后这些字段会变成 undefined"
    )


def metric_snapshot_payload() -> dict:
    """一个空快照经 WebSocket Hub 序列化后的载荷（不需要 Hub 实例状态）。"""
    payload = WebSocketHub.snapshot_payload(MetricSnapshot())
    return json.loads(json.dumps(payload, default=str))


def test_snapshot_payload_has_every_overview_field():
    """快照载荷的键集合必须覆盖 ``/api/overview`` 的契约。

    修复前 ``branding`` / ``health`` 缺失、``thresholds`` 存在但是空字典。
    """
    payload = metric_snapshot_payload()
    missing = sorted(set(OVERVIEW_FIELDS) - set(payload))
    assert not missing, f"快照载荷缺少 /api/overview 契约字段：{missing}"
    #: 对外键名必须是 self（而不是 self_info）—— 前端只认一个名字
    assert "self" in payload, "快照载荷必须把 self_info 改名成 self"
    assert "self_info" not in payload, "不得同时下发 self_info，前端会读错"


def test_snapshot_payload_does_not_leak_internal_field_name():
    """反向断言：内部字段名 ``self_info`` 不得出现在载荷里。"""
    assert "self_info" not in metric_snapshot_payload()


def test_health_payload_keys_match_contract():
    """``health`` 的键集合与 ``HEALTH_FIELDS`` 严格一致。"""
    fake = type("A", (), {"ready": lambda self: (True, []), "ready_codes": lambda self: (True, [])})()
    from app.payload import health_of

    got = health_of(fake)
    assert set(got) == set(HEALTH_FIELDS), f"health 载荷键与契约不符：{sorted(got)}"
    assert got["ready"] is True
    assert got["reason_codes"] == []
    #: 拿不到 Hub 统计时也要给零值占位，保证字段恒定存在（前端不必判空）
    assert got["ws"]["metrics_clients"] == 0


def test_health_reason_codes_survive_into_payload():
    """降级原因码必须能穿过聚合器进入快照 —— 这是横幅显示与否的唯一依据。

    修复前 ``health`` 根本不在快照里，``o.health || {}`` ⇒ 横幅永不出现。
    """

    class _Stale:
        stale = True
        last_error = "connection refused"

    class _Journal:
        running = False

    class _FakeAgg:
        """只实现 ready()/ready_codes() 依赖的三个属性。"""

        slots = type("X", (), {"state": _Stale()})()
        gpu = type("X", (), {"state": type("Y", (), {"stale": False, "last_error": ""})()})()
        journal = _Journal()

        def ready(self):
            from app.services.aggregator import Aggregator

            return Aggregator.ready(self)

        def ready_codes(self):
            from app.services.aggregator import Aggregator

            return Aggregator.ready_codes(self)

    from app.payload import health_of

    h = health_of(_FakeAgg())
    assert h["ready"] is False, "slots 陈旧时 ready 必须为 False"
    assert "slots_unavailable" in h["reason_codes"], "必须给出语言无关原因码"
    assert not re.search(r"[\u4e00-\u9fff]", "".join(h["reason_codes"])), "原因码不得含中文"


def test_rest_and_ws_same_snapshot_via_route_call(tmp_path):
    """以同一个快照分别走 REST 路由与 WS 序列化，键集合必须完全相等。

    **这是修复的核心判据**：两条路径 dump 的是同一个 ``MetricSnapshot``；
    修复前 REST 多出 ``branding`` / ``thresholds`` / ``health``，
    WS 缺这三个（``thresholds`` 存在但是空字典）。

    不用 ``TestClient``：本测试要的是"两条路径处理同一份数据"，
    而不是"HTTP 层能否工作"。用假 Request 更稳定，也不会触发 lifespan。
    """
    import asyncio

    from app.config import Settings
    from app.main import build_container
    from app.payload import OVERVIEW_FIELDS as _fields  # noqa: F401
    from app.routes.overview import overview

    c = build_container(Settings(state_dir=str(tmp_path / "state"), llama_base_url="http://127.0.0.1:8080"))
    c.aggregator.snapshot = c.aggregator._build(0, c.hub.stats())

    class _State:
        ctx = c

    class _App:
        state = _State()

    class _Req:
        app = _App()

    rest = asyncio.run(overview(_Req()))
    ws = WebSocketHub.snapshot_payload(c.aggregator.snapshot)

    assert set(rest) == set(ws), (
        "REST 与 WS 的顶层键集合必须完全相等 —— "
        f"只在 REST 出现：{sorted(set(rest) - set(ws))}；"
        f"只在 WS 出现：{sorted(set(ws) - set(rest))}"
    )

    #: 形状对、内容是空 —— 这正是修复前的状态，必须一并断言
    assert rest["thresholds"], "thresholds 不得为空字典（否则前端退回硬编码）"
    assert rest["branding"], "branding 不得为空字典"
    assert rest["health"], "health 不得为空字典"
    assert "ready" in rest["health"] and "reason_codes" in rest["health"]
    #: 派生展示字段仍在
    assert "full_name" in rest["model"] and "path" in rest["model"]
