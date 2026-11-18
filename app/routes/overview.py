"""GET /api/overview —— 首屏一次返回全部指标（方案 7.2 / 7.3.1；v0.4 增量）。

v0.4 增量（均为**加法**，v0.1 已有字段一个不动）：
  * ``thresholds`` 补全前端用到的全部阈值 —— 前端不再硬编码（F5 / TASK-27）
  * ``accelerator_badge`` 顶栏算力卡摘要（R1）
  * ``model.full_name`` / ``model.path`` 顶栏模型全称（R2）
  * ``baseline`` 自动基线状态（§7）
  * ``llama_uptime_s`` 顶栏「服务运行」（决策 B1）

v0.6.1 重构（**行为修复**，字段一个不少）
------------------------------------------

原先本路由**手工拼** ``branding`` / ``thresholds`` / ``health``，而 WebSocket 推的是
``MetricSnapshot.model_dump()`` —— 两条路径字段集不一致，前端却用**同一个**
``renderOverview()`` 处理。后果是页面每 2 秒被推送覆盖一次：

  * ``state.thresholds`` 被写成 ``undefined || {}`` ⇒ 阈值改了不起作用；
  * ``o.health`` 变成 ``undefined`` ⇒ 降级横幅永不出现、总状态永远显示 ok。

现在载荷**只有一处来源**：``snapshot.model_dump()``（在 ``app/models.py`` 上定义）。
本路由只补两个**纯展示派生字段**（``model.full_name`` / ``model.path``），
它们不属于采集结果，因此不进快照模型。

判据：``tests/test_overview_ws_parity.py`` 断言 REST 与 WS 的**顶层键集合完全相等**，
且前端读取的每个键都真实存在。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..payload import thresholds_of
from ._deps import ctx

router = APIRouter()

#: 供 ``tests/`` 与其它模块导入的历史入口。
#:
#: 实现已移到 ``app/payload.py``（聚合器也要用它，见该模块文件头为何必须共用）：
#: 放在路由层会让 ``app.services.aggregator`` 反向依赖路由，形成导入环。
#: 注意签名变为 ``thresholds_of(settings, baselines)`` —— 直接收两个对象，
#: 避免"容器属性名在路由叫 c.settings、在聚合器叫 self.s"的鸭子类型猜测。
__all__ = ["router", "thresholds_of"]


@router.get("/api/overview")
async def overview(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    #: 全量载荷来自快照 —— 与 WebSocket **同一份数据**，不可能再漂移。
    payload: dict = snap.model_dump()
    #: R2：顶栏需要"全称"与完整路径（派生展示字段，不进快照模型）
    payload["model"] = dict(payload["model"], full_name=snap.model.name, path=c.props_model_path())
    #: ``self_info`` → ``self``：与 WebSocket 保持同一字段名
    payload["self"] = payload.pop("self_info")
    return payload
