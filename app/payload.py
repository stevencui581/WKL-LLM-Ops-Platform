"""快照的**非采集类**字段：阈值、品牌、健康度。

这个模块存在的唯一理由，是让 **REST 与 WebSocket 共用同一份构造逻辑**。

**真实缺陷（v0.6 已知，本文档写作时修复）**

    ``/api/overview`` 的载荷里，``branding`` / ``thresholds`` / ``health`` 是
    **路由里手工拼的**，而 WebSocket 推的是 ``MetricSnapshot.model_dump()``。
    两条路径的字段集不一致，而前端**同一个** ``renderOverview()`` 处理两者 ——
    于是页面每 2 秒被推送覆盖一次：

      * ``state.thresholds`` 被写成 ``undefined || {}`` ⇒ 阈值改了不起作用；
      * ``o.health`` 变成 ``undefined`` ⇒ 降级横幅永不出现、总状态永远显示 ok。

    这与 v0.5 的「框架徽标一直显示识别中」是**同一个根因**（见
    ``tests/test_snapshot_fields.py`` 的文件头），只是那次只修了 ``framework``
    一个字段，没有把「两条路径必须同源」变成结构性保证。

**现在的结构**

    这三个字段都由本模块构造，并且**都随快照下发**：

      * ``thresholds_of()`` → 聚合器写进 ``MetricSnapshot.thresholds``
      * ``branding_of()``   → 聚合器写进 ``MetricSnapshot.branding``
      * ``health_of()``     → 聚合器写进 ``MetricSnapshot.health``

    路由只做一件事：``snap.model_dump()`` + 补 ``model.full_name`` / ``model.path``。
    于是 REST 与 WS **物理上不可能再漂移** —— 它们 dump 的是同一个模型。

本模块只依赖 ``app.config``（``Settings``）与鸭子类型的容器，**不导入**
``app.routes`` / ``app.services``，因此不会产生导入环。
"""

from __future__ import annotations

from typing import Any

#: ``health.ws`` 在拿不到 Hub 统计时的占位（聚合器单独构造快照时会用不到）。
_WS_UNKNOWN: dict[str, Any] = {
    "metrics_clients": 0,
    "logs_clients": 0,
    "total_dropped": 0,
}


#: ``health`` 载荷的完整键集合（**契约**）。
#:
#: 显式声明而不是靠字符串散落在各处：守卫 ``test_overview_keeps_v01_fields``
#: 与本模块的 ``health_of()`` 都读它，前后端契约因此只有一个来源。
HEALTH_FIELDS: dict[str, str] = {
    "ready": "总体是否就绪",
    "reasons": "中文原因串（兼容旧前端）",
    "reason_codes": "语言无关原因码（前端按当前语言本地化）",
    "ws": "WebSocket 连接统计",
}

#: ``/api/overview`` 顶层字段契约（v0.1 起向后兼容，只增不减）。
#:
#: 与 ``MetricSnapshot`` 一一对应（``self_info`` 对外叫 ``self``）；
#: ``model`` 另有两个派生展示字段 ``full_name`` / ``path``，在路由里补。
OVERVIEW_FIELDS: tuple[str, ...] = (
    "ts",
    "seq",
    "stale",
    "model",
    "kpi",
    "kv",
    "runtime",
    "system",
    "self",
    "alerts",
    "gpus",
    "branding",
    "thresholds",
    "health",
    "baseline",
    "accelerator_badge",
    "llama_uptime_s",
    "hardware_ts",
    "framework",
)


def thresholds_of(settings: Any, baselines: Any = None) -> dict:
    """前端渲染与告警判定需要的**全部**阈值，一次性下发。

    前端不得再出现 95 / 85 / 87 / 83 之类的魔法数字（F5 修复）。

    参数是 **settings 与 baselines 两个对象本身**（而不是容器）——
    这样聚合器（持有的属性名是 ``self.s``）与路由（持有的属性名是
    ``c.settings``）都能直接调用，不需要任何适配层或鸭子类型猜测。
    """
    s = settings
    return {
        # 告警阈值
        "gpu_temp_warn_c": s.gpu_temp_warn_c,
        "gpu_temp_crit_c": s.gpu_temp_crit_c,
        "vram_warn_pct": s.vram_warn_pct,
        "vram_crit_pct": s.vram_crit_pct,
        "kv_warn_pct": s.kv_warn_pct,
        "kv_crit_pct": s.kv_crit_pct,
        "power_warn_pct": s.power_warn_pct,
        "mtp_drop_ratio": s.mtp_drop_ratio,
        "decode_drop_ratio": s.decode_drop_ratio,
        # 卡片配色阈值（与告警阈值分开）
        "vram_color_warn_pct": s.vram_color_warn_pct,
        # 自动基线（可能为 None = 学习中）
        "mtp_accept_baseline": baselines.mtp_baseline if baselines else None,
        "decode_baseline_tps": baselines.decode_baseline if baselines else None,
        # 刷新频率（顶栏/底栏文案由前端按此显示）
        "poll_interval_s": s.poll_interval_s,
        "history_points": s.history_points,
        # 自身开销守护
        "self_cpu_warn_pct": s.self_cpu_warn_pct,
        "self_rss_warn_mb": s.self_rss_warn_mb,
    }


def branding_of(s: Any) -> dict:
    """品牌信息（产品名/版本/开发者）。

    v0.4.3 §6.5：版号只从后端下发，前端不写死 —— 否则页面会显示旧版号。
    """
    return {
        "product_name": s.product_name,
        "product_name_spaced": s.product_name_spaced,
        "product_version": s.product_version,
        "developer": s.developer,
        "develop_date": s.develop_date,
    }


def health_of(aggregator: Any, ws_stats: dict | None = None) -> dict:
    """就绪状态（``/api/health`` 的同源子集）。

    ``reason_codes`` 是**语言无关**的（v0.4.3 §6.4），前端按当前语言本地化；
    ``reasons`` 的中文串保留作兼容。

    ``ws`` 需要 WebSocket Hub 的统计，而聚合器不持有 Hub，因此由调用方
    （``app/main.py`` 的采集循环）通过 ``ws_stats`` 传入；拿不到时给零值占位，
    保证**字段名恒定存在** —— 前端因此不需要判空分支。
    """
    ready, reasons = aggregator.ready()
    _ready_codes, codes = aggregator.ready_codes()
    #: 键集合与 ``HEALTH_FIELDS`` 严格一致（多一个少一个都算破坏契约）——
    #: 由 ``tests/test_overview_ws_parity.py`` 断言，而不是靠字符串散落各处。
    return {
        "ready": ready,
        "reasons": reasons,
        "reason_codes": codes,
        "ws": dict(ws_stats) if ws_stats else dict(_WS_UNKNOWN),
    }
