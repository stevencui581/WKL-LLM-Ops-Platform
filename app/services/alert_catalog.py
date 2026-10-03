"""告警目录（TASK-49 / v0.4.3 §6.1）。

职责：把**告警代码**翻译成运维看得懂的「服务类型 + 服务名称」，并提供中英双语。

设计要点（v0.4 原则 P5：数据表驱动）：
  * 新增一个告警只需在 ``ALERT_CATALOG`` 加一行，**不需要改任何判断逻辑**；
  * 这里同时是**告警代码的权威清单** —— 测试据此断言"没有漏翻译的告警"；
  * 中文名用于向后兼容的旧字段（``Alert.message`` 等），
    双语名通过 ``GET /api/alert-catalog`` 一次性下发给前端，
    前端按当前语言渲染 —— **语言属于展示层**，不在后端拼句子。

术语（v0.4.3 §5，甲方指定）：
  「算力卡」英文一律为 **compute card**，不得写成 accelerator / GPU card。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlertMeta:
    """单个告警的元信息。"""

    code: str
    category_zh: str
    category_en: str
    name_zh: str
    name_en: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "category": {"zh": self.category_zh, "en": self.category_en},
            "name": {"zh": self.name_zh, "en": self.name_en},
        }


#: 未知告警代码的兜底：显示代码本身，**不编造**名称（原则 P3）
UNKNOWN_CATEGORY = {"zh": "未分类", "en": "Uncategorized"}


def _m(code: str, cz: str, ce: str, nz: str, ne: str) -> tuple[str, AlertMeta]:
    return code, AlertMeta(code, cz, ce, nz, ne)


#: 告警目录 —— 权威清单（14 项，与 app/services/alerts.py 一一对应）
ALERT_CATALOG: dict[str, AlertMeta] = dict(
    [
        # ---- 推理服务 ----
        _m("SERVICE_DOWN", "推理服务", "Inference service", "服务不可用", "Service unreachable"),
        _m("PROC_EXIT", "推理服务", "Inference service", "进程退出", "Process exited"),
        # ---- 算力卡（英文按甲方要求固定为 compute card）----
        _m("GPU_TEMP_CRIT", "算力卡", "Compute card", "GPU 温度过高", "GPU temperature critical"),
        _m("GPU_TEMP_WARN", "算力卡", "Compute card", "GPU 温度偏高", "GPU temperature high"),
        _m("GPU_POWER", "算力卡", "Compute card", "GPU 功耗接近上限", "GPU power near limit"),
        # ---- 显存 ----
        _m("VRAM_CRIT", "显存", "VRAM", "显存占用过高", "VRAM usage critical"),
        _m("VRAM_WARN", "显存", "VRAM", "显存占用偏高", "VRAM usage high"),
        # ---- KV 缓存 ----
        _m("KV_CRIT", "KV 缓存", "KV cache", "KV 池将满", "KV cache nearly full"),
        _m("KV_WARN", "KV 缓存", "KV cache", "KV 池占用偏高", "KV cache usage high"),
        # ---- 模型性能 ----
        _m("MTP_LOW", "模型性能", "Model performance", "MTP 接受率下滑", "MTP acceptance dropped"),
        _m("DECODE_LOW", "模型性能", "Model performance", "解码速率下滑", "Decode rate dropped"),
        # ---- 请求处理 ----
        _m("REQ_DEFERRED", "请求处理", "Request handling", "请求排队", "Requests queued"),
        _m("CTX_TRUNCATED", "请求处理", "Request handling", "上下文被截断", "Context truncated"),
        _m("CLIENT_CANCEL", "请求处理", "Request handling", "客户端取消生成", "Client cancelled generation"),
    ]
)

#: 全部告警代码（有序，便于展示与测试）
ALL_CODES: tuple[str, ...] = tuple(ALERT_CATALOG)

#: 级别中文名（旧字段兼容用）
LEVEL_ZH = {"info": "提示", "warning": "警告", "critical": "严重"}


def meta(code: str) -> AlertMeta:
    """取告警元信息；**未知代码返回代码本身作为名称，不猜测**。"""
    got = ALERT_CATALOG.get(code)
    if got is not None:
        return got
    return AlertMeta(
        code=code,
        category_zh=UNKNOWN_CATEGORY["zh"],
        category_en=UNKNOWN_CATEGORY["en"],
        name_zh=code,
        name_en=code,
    )


def category(code: str, lang: str = "zh") -> str:
    m = meta(code)
    return m.category_en if lang == "en" else m.category_zh


def name(code: str, lang: str = "zh") -> str:
    m = meta(code)
    return m.name_en if lang == "en" else m.name_zh


def catalog_payload() -> dict:
    """下发给前端的完整目录（一次性获取，前端按语言渲染）。"""
    return {
        "codes": {c: m.as_dict() for c, m in ALERT_CATALOG.items()},
        "unknown_category": dict(UNKNOWN_CATEGORY),
        "level_zh": dict(LEVEL_ZH),
    }
