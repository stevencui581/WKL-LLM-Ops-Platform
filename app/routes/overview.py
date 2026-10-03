"""GET /api/overview —— 首屏一次返回全部指标（方案 7.2 / 7.3.1；v0.4 增量）。

v0.4 增量（均为**加法**，v0.1 已有字段一个不动）：
  * ``thresholds`` 补全前端用到的全部阈值 —— 前端不再硬编码（F5 / TASK-27）
  * ``accelerator_badge`` 顶栏算力卡摘要（R1）
  * ``model.full_name`` / ``model.path`` 顶栏模型全称（R2）
  * ``baseline`` 自动基线状态（§7）
  * ``llama_uptime_s`` 顶栏「服务运行」（决策 B1）
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ._deps import ctx

router = APIRouter()


def thresholds_of(c) -> dict:
    """前端渲染与告警判定需要的**全部**阈值，一次性下发。

    前端不得再出现 95 / 85 / 87 / 83 之类的魔法数字（F5 修复）。
    """
    s = c.settings
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
        "mtp_accept_baseline": c.baselines.mtp_baseline if c.baselines else None,
        "decode_baseline_tps": c.baselines.decode_baseline if c.baselines else None,
        # 刷新频率（顶栏/底栏文案由前端按此显示）
        "poll_interval_s": s.poll_interval_s,
        "history_points": s.history_points,
        # 自身开销守护
        "self_cpu_warn_pct": s.self_cpu_warn_pct,
        "self_rss_warn_mb": s.self_rss_warn_mb,
    }


@router.get("/api/overview")
async def overview(request: Request) -> dict:
    c = ctx(request)
    snap = c.aggregator.snapshot
    model = snap.model.model_dump()
    # R2：顶栏需要"全称"与完整路径
    model["full_name"] = model.get("name", "")
    model["path"] = c.props_model_path()
    return {
        "ts": snap.ts,
        "seq": snap.seq,
        "stale": snap.stale,
        "branding": {
            "product_name": c.settings.product_name,
            "product_name_spaced": c.settings.product_name_spaced,
            "product_version": c.settings.product_version,
            "developer": c.settings.developer,
            "develop_date": c.settings.develop_date,
        },
        "model": model,
        "kpi": snap.kpi.model_dump(),
        "kv": snap.kv.model_dump(),
        "runtime": snap.runtime.model_dump(),
        "system": snap.system.model_dump(),
        "self": snap.self_info.model_dump(),
        "alerts": [a.model_dump() for a in snap.alerts],
        "gpus": [g.model_dump() for g in snap.gpus],
        "accelerator_badge": snap.accelerator_badge.model_dump(),
        "baseline": snap.baseline.model_dump(),
        "llama_uptime_s": snap.llama_uptime_s,
        "hardware_ts": snap.hardware_ts,
        #: v0.5 §1：推理框架识别结果（llama.cpp / ollama / vLLM / SGLang / …）
        #: 中英文都给，前端按当前语言渲染 —— 页面不写死任何框架名。
        #: **取自快照**：REST 与 WebSocket 必须是同一数据源，否则页面每 2 秒
        #: 被推送覆盖后，「框架」徽标会退回占位文案并永久停在那里（实测踩过的坑）。
        "framework": snap.framework,
        "thresholds": thresholds_of(c),
        "health": {
            "ready": c.aggregator.ready()[0],
            "reasons": c.aggregator.ready()[1],
            #: v0.4.3 §6.4：语言无关的降级原因码，前端按当前语言渲染
            "reason_codes": c.aggregator.ready_codes()[1],
            "ws": c.hub.stats(),
        },
    }
