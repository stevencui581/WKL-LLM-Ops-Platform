"""Collector-D：/props 与 /v1/models 配置采集器（方案 TASK-05）。

提供运行时配置徽标数据与 KV 分母；60 秒采集一次，但对首屏必须立即采一次。
"""

from __future__ import annotations

import time

from ..adapters.llama import LlamaClient
from ..config import Settings
from ..models import ModelInfo, RuntimeConfig
from ..services import accel, gpu_spec
from ..services.unitinfo import UnitConfig
from .base import CollectorState


def parse_props(props: dict | None) -> dict:
    p = props or {}
    gen = p.get("default_generation_settings") or {}
    params = gen.get("params") or {}
    return {
        "total_slots": int(p.get("total_slots") or 0),
        "n_ctx": int(gen.get("n_ctx") or 0),
        "model_ftype": str(p.get("model_ftype") or ""),
        "model_path": str(p.get("model_path") or ""),
        "endpoint_slots": bool(p.get("endpoint_slots")),
        "endpoint_props": bool(p.get("endpoint_props")),
        "endpoint_metrics": bool(p.get("endpoint_metrics")),
        "ui": bool(p.get("ui")),
        "spec_types": str(params.get("speculative.types") or ""),
        "cache_type_k": str(params.get("cache_type_k") or ""),
        "cache_type_v": str(params.get("cache_type_v") or ""),
        "flash_attn": bool(params.get("flash_attn", True)),
    }


def parse_models(payload: dict | None) -> ModelInfo:
    data = (payload or {}).get("data") or []
    meta: dict = {}
    name = ""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        name = str(first.get("id") or "")
        meta = first.get("meta") or {}
    return ModelInfo(
        name=name.rsplit("/", 1)[-1] if name else "",
        ftype=str(meta.get("ftype") or ""),
        n_params=int(meta.get("n_params") or 0),
        n_ctx=int(meta.get("n_ctx") or 0),
        n_ctx_train=int(meta.get("n_ctx_train") or 0),
        n_vocab=int(meta.get("n_vocab") or 0),
        size_bytes=int(meta.get("size") or 0),
    )


class PropsCollector:
    name = "props"

    def __init__(self, settings: Settings, client: LlamaClient):
        self.s = settings
        self.client = client
        state_key = "config"
        self.state = CollectorState(state_key, settings.stale_after_misses)
        self.props: dict = {}
        self.model = ModelInfo()
        self._last_ok_mono: float = 0.0
        self.ready = False
        #: v0.5：当前框架是否提供 /props（ollama 等没有）与 /v1/models。
        #: 两者都没有时，本采集器不再探测，也不算故障。
        self.has_props: bool = True
        self.has_models: bool = True

    def set_capabilities(self, has_props: bool, has_models: bool) -> None:
        if (has_props, has_models) != (self.has_props, self.has_models):
            self.has_props, self.has_models = has_props, has_models
            self.ready = False
            self.state.reset()
            if not has_models:
                self.model = ModelInfo()

    def due(self) -> bool:
        if not self.ready:
            return True
        return (time.monotonic() - self._last_ok_mono) >= self.s.config_poll_interval_s

    async def collect(self, force: bool = False) -> bool:
        if not (self.has_props or self.has_models):
            return True  # 框架不提供配置类接口，跳过且不报故障
        if not force and not self.due():
            return True
        t0 = time.monotonic()
        ok_p, props, err_p = await self.client.props() if self.has_props else (False, None, None)
        ok_m, models, err_m = await self.client.models() if self.has_models else (False, None, None)
        if not ok_p and not ok_m:
            self.state.fail(err_p or err_m or "props+models unavailable")
            return False
        if ok_p:
            self.props = parse_props(props)
        if ok_m:
            self.model = parse_models(models)
        # KV 分母优先取 /props 的 n_ctx；缺失时退回 /v1/models 的 n_ctx
        if not self.props.get("n_ctx") and self.model.n_ctx:
            self.props["n_ctx"] = self.model.n_ctx
        self._last_ok_mono = time.monotonic()
        self.ready = True
        self.state.ok((time.monotonic() - t0) * 1000.0)
        return True

    @property
    def metrics_enabled(self) -> bool:
        return bool(self.props.get("endpoint_metrics"))

    @property
    def total_ctx(self) -> int:
        return int(self.props.get("n_ctx") or 0)

    def runtime_config(
        self,
        gpu_count: int,
        unit: UnitConfig | None = None,
        slot_spec_types: str = "",
        gpu_name: str = "",
        platform: str = "",
    ) -> RuntimeConfig:
        """生成运行时配置徽标。

        取值优先级（均为实测结论）：
          * 投机解码类型：unit 的 ``--spec-type`` 最权威；
            ``/slots`` 的槽位 params 次之（只在有任务时有值）；
            ``/props`` 的默认值最弱（实测恒为 "none"）。
          * draft 上限 / FlashAttn / tensor-split / KV 量化：以 unit 为准。
          * 上下文 / 槽位总数：以 ``/props`` 为准。

        v0.4 F16：KV 量化**不再硬编码兜底 "f16"** —— ``/props`` 实测不返回
        ``cache_type_k/v``。改为读 unit 的 ``-ctk/-ctv``；未配置时按
        ``kv_quant_show_default`` 显示「f16（默认）」或「未知」，并带来源标记。
        """
        p = self.props
        u = unit or UnitConfig()
        spec = slot_spec_types or u.spec_type or p.get("spec_types") or ""
        draft_n_max = u.draft_n_max
        flash = u.flash_attn if u.flash_attn is not None else bool(p.get("flash_attn"))
        tensor_split = u.tensor_split or "1,1"
        n_ctx = int(p.get("n_ctx") or u.n_ctx or self.model.n_ctx or 0)
        slots_total = int(p.get("total_slots") or u.parallel or 0)

        kv_label, kv_source, kv_raw = self._kv_quant(u, p)

        badges: list[str] = []
        # v0.4.3 §6.4：结构化徽标 —— 后端只给 key/value，语言由前端决定。
        # 旧的 badges（中文串）保留作向后兼容（curl / 非 JS 消费者可读）。
        items: list[dict] = []
        badges.append(f"KV 量化 {kv_label}")
        items.append({"key": "kv_quant", "value": kv_raw, "source": kv_source})
        if n_ctx:
            badges.append(f"上下文 {n_ctx // 1024}K")
            items.append({"key": "n_ctx", "value": str(n_ctx // 1024), "source": "unit"})
        if spec and spec != "none":
            badges.append(f"投机解码 {spec}")
            items.append({"key": "spec", "value": spec, "source": "unit"})
        elif spec == "none":
            badges.append("投机解码 关闭")
            items.append({"key": "spec_off", "value": "", "source": "unit"})
        if draft_n_max:
            badges.append(f"draft {draft_n_max}(+1)")
            items.append({"key": "draft", "value": str(draft_n_max), "source": "unit"})
        badges.append("FlashAttn 开" if flash else "FlashAttn 关")
        items.append({"key": "flash_on" if flash else "flash_off", "value": "", "source": "unit"})
        if self.model.ftype:
            badges.append(f"模型 {self.model.ftype}")
            items.append({"key": "model_ftype", "value": self.model.ftype, "source": "props"})
        if gpu_count:
            badges.append(f"{gpu_count} 卡 tensor-split {tensor_split}")
            items.append({"key": "tensor_split", "value": f"{gpu_count}|{tensor_split}", "source": "unit"})

        return RuntimeConfig(
            product_name=self.s.product_name,
            product_version=self.s.product_version,
            model_name=self.model.name or (p.get("model_path") or "").rsplit("/", 1)[-1],
            model_ftype=self.model.ftype or p.get("model_ftype", ""),
            n_ctx=n_ctx,
            n_ctx_train=self.model.n_ctx_train,
            total_slots=slots_total,
            kv_quant=kv_label,
            kv_quant_source=kv_source,
            badge_items=items,
            spec_types=spec,
            draft_n_max=draft_n_max,
            flash_attn=flash,
            tensor_split=tensor_split,
            split_mode=u.split_mode,
            tensor_parallel=u.tensor_parallel,
            gpu_count=gpu_count,
            gpu_bandwidth_label=gpu_spec.bandwidth_label(gpu_name) if gpu_name else "",
            metrics_enabled=self.metrics_enabled,
            slots_enabled=bool(p.get("endpoint_slots")),
            ui_enabled=bool(p.get("ui")),
            platform=platform or (f"{accel.VENDOR_DISPLAY.get('nvidia')} CUDA" if gpu_count else ""),
            badges=badges,
        )

    def _kv_quant(self, u: UnitConfig, p: dict) -> tuple[str, str, str]:
        """KV 量化类型与来源（v0.4 F16 修复；v0.4.3 增加裸值）。

        返回 ``(显示文本, 来源, 裸值)``：
          * 显示文本 —— 中文兼容串（如 ``f16（默认）``），供 curl / 非 JS 消费者；
          * 来源 —— ``unit`` / ``default`` / ``unknown``；
          * **裸值** —— 不含「（默认）」等修饰的纯技术值（如 ``f16``），
            供前端按当前语言自行加标注（v0.4.3 §6.4 数据与展示分离）。

        ``/props`` 只在确实返回了 ``cache_type_k/v`` 时才采信（实测不返回）。
        """
        k, v = u.cache_type
        if k or v:
            raw = f"{k or 'f16'}/{v or 'f16'}"
            return raw, "unit", raw
        pk, pv = p.get("cache_type_k"), p.get("cache_type_v")
        if pk or pv:
            raw = f"{pk or 'f16'}/{pv or 'f16'}"
            return raw, "unit", raw
        if u.readable and self.s.kv_quant_show_default:
            # llama.cpp 未指定 -ctk/-ctv 时默认 f16；如实标注为「默认」而非探测值
            return "f16（默认）", "default", "f16"
        return "", "unknown", ""
