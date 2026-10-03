"""算力卡规格表 —— 按型号特征匹配，**数据表驱动**（v0.4 F2 修复 / 原则 P5）。

设计要点：
  * 这里是**唯一**允许出现具体显卡型号的地方，且它是"规格字典"而非"事实"：
    只有当实际探测到的型号命中时才取值，未命中一律返回 None；
  * 未命中时界面显示「—」，**绝不复用其它卡的数值**（原则 P3）；
  * 新增卡型只需在 ``GPU_SPECS`` 加一行，不需要改任何判断逻辑。

v0.1 的问题：``gpu.py`` 里写死 ``V100_BANDWIDTH_GBPS = 900.0`` 并套用到所有卡，
换 A100/4090 后带宽全算错。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuSpec:
    """一种显卡的规格。``patterns`` 为型号特征（小写子串，按顺序前缀匹配）。"""

    patterns: tuple[str, ...]
    bandwidth_gbps: float
    mem_type: str = ""
    vendor: str = "nvidia"


#: 规格表。匹配规则：把探测到的型号名转小写，依次比对 patterns 中的子串。
GPU_SPECS: tuple[GpuSpec, ...] = (
    # ---- NVIDIA 数据中心 ----
    GpuSpec(("tesla v100", "v100"), 900.0, "HBM2"),
    GpuSpec(("a100",), 1555.0, "HBM2e"),
    GpuSpec(("h100",), 3350.0, "HBM3"),
    GpuSpec(("h200",), 4800.0, "HBM3e"),
    GpuSpec(("a800",), 1555.0, "HBM2e"),
    GpuSpec(("a40",), 696.0, "GDDR6"),
    GpuSpec(("a30",), 933.0, "HBM2"),
    GpuSpec(("a10",), 600.0, "GDDR6"),
    GpuSpec(("l40s", "l40"), 864.0, "GDDR6"),
    GpuSpec(("l4",), 300.0, "GDDR6"),
    GpuSpec(("t4",), 320.0, "GDDR6"),
    GpuSpec(("a6000",), 768.0, "GDDR6"),
    GpuSpec(("a5000",), 768.0, "GDDR6"),
    GpuSpec(("a4000",), 448.0, "GDDR6"),
    GpuSpec(("v100",), 900.0, "HBM2"),
    # ---- NVIDIA 消费级 ----
    GpuSpec(("rtx 5090",), 1792.0, "GDDR7"),
    GpuSpec(("rtx 4090",), 1008.0, "GDDR6X"),
    GpuSpec(("rtx 4080",), 717.0, "GDDR6X"),
    GpuSpec(("rtx 3090",), 936.0, "GDDR6X"),
    GpuSpec(("rtx 3080",), 760.0, "GDDR6X"),
    GpuSpec(("rtx 3060",), 360.0, "GDDR6"),
    # ---- AMD Instinct ----
    GpuSpec(("mi300",), 5300.0, "HBM3", "amd"),
    GpuSpec(("mi250",), 3277.0, "HBM2e", "amd"),
    GpuSpec(("mi210",), 1638.0, "HBM2e", "amd"),
    GpuSpec(("mi100",), 1229.0, "HBM2", "amd"),
    # ---- AMD Radeon ----
    GpuSpec(("radeon pro w7900",), 864.0, "GDDR6", "amd"),
    GpuSpec(("radeon pro w6800",), 512.0, "GDDR6", "amd"),
    GpuSpec(("7900 xtx",), 960.0, "GDDR6", "amd"),
)


def lookup(name: str) -> GpuSpec | None:
    """按型号名查规格；查不到返回 ``None``（**不返回任何默认值**）。

    >>> lookup("Tesla V100-SXM2-16GB").bandwidth_gbps
    900.0
    >>> lookup("Some Unknown Card 9000") is None
    True
    """
    if not name:
        return None
    low = name.strip().lower()
    for spec in GPU_SPECS:
        for pat in spec.patterns:
            if pat in low:
                return spec
    return None


def bandwidth_of(name: str) -> float | None:
    """型号 → 峰值带宽（GB/s）。查不到返回 ``None``。"""
    spec = lookup(name)
    return spec.bandwidth_gbps if spec else None


def mem_type_of(name: str) -> str:
    spec = lookup(name)
    return spec.mem_type if spec else ""


def vendor_of(name: str) -> str:
    spec = lookup(name)
    return spec.vendor if spec else ""


def approx_bandwidth(name: str, util_mem_pct: float | None) -> float | None:
    """近似带宽 = 峰值 × 显存控制器利用率。峰值未知时返回 ``None``。"""
    peak = bandwidth_of(name)
    if peak is None or util_mem_pct is None:
        return None
    return round(peak * util_mem_pct / 100.0, 1)


def bandwidth_label(name: str) -> str:
    """供界面显示的峰值说明文案。未知型号如实说明，不编造。"""
    spec = lookup(name)
    if spec is None:
        return "峰值带宽未知（型号未收录）"
    return f"{spec.mem_type or '显存'} 峰值 {spec.bandwidth_gbps:.0f} GB/s"
