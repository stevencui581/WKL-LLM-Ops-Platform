"""算力卡厂家探测与条件渲染判定（v0.4 §5.2 / §6.3 / TASK-32 / F12 修复）。

v0.1 的 GPU 采集器是 **nvidia-smi 专用**：AMD 服务器上 GPU 面板全空。
本模块把"怎么发现算力卡"和"用哪个工具"分开：

    ① ``lspci -nn`` 发现所有 PCI 显示/加速设备（厂家中立）
    ② 按白名单厂商 ID 过滤，排除虚拟显卡（QEMU 1234:1111 之类）
    ③ 有对应厂家的卡，才启用该厂家的采集通路（nvidia-smi / rocm-smi）
    ④ 没有的厂家，前端**整段不渲染**（R4）

这样换 AMD 机器时 NVIDIA 段落消失、ROCm 段落出现，反之亦然。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: PCI 厂商 ID → 厂家名
VENDOR_NAMES = {
    "10de": "nvidia",
    "1002": "amd",
    "1022": "amd",
}

#: 产出可展示名称
VENDOR_DISPLAY = {"nvidia": "NVIDIA", "amd": "AMD"}

#: 驱动名（内核模块）——常量映射，与具体型号无关
VENDOR_DRIVER = {"nvidia": "nvidia", "amd": "amdgpu"}

RE_LSPCI_ACCEL = re.compile(
    r"^(?P<addr>[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])"
    r"\s+(?P<cls>[^:]+):\s+"
    r"(?P<desc>.+?)"
    r"(?:\s+\[(?P<vendor>[0-9a-f]{4}):(?P<device>[0-9a-f]{4})\])?"
    r"(?:\s+\(rev .*?\))?\s*$",
    re.I,
)

#: 需要关注的 PCI 设备类别关键字
ACCEL_CLASS_HINTS = ("vga", "3d controller", "display controller", "processing accel")


@dataclass
class PciAccel:
    address: str
    description: str
    vendor_id: str
    device_id: str
    vendor: str  # nvidia / amd / unknown

    @property
    def pci_id(self) -> str:
        return f"{self.vendor_id}:{self.device_id}"


@dataclass
class VendorScan:
    """一次 lspci 扫描的结果。"""

    devices: list[PciAccel] = field(default_factory=list)
    vendors: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    error: str = ""

    def count_of(self, vendor: str) -> int:
        return sum(1 for d in self.devices if d.vendor == vendor)

    def models_of(self, vendor: str) -> list[str]:
        return [d.description for d in self.devices if d.vendor == vendor]


def _clean_desc(desc: str) -> str:
    """去掉 lspci 描述里的括号补充信息，留下型号主体。"""
    d = re.sub(r"\s*\[[^\]]*\]\s*", " ", desc or "")
    d = re.sub(r"\s+", " ", d).strip()
    return d


def parse_lspci(
    text: str, allowlist: tuple[str, ...] = ("10de", "1002"), denylist: tuple[str, ...] = ("1234:1111",)
) -> VendorScan:
    """解析 ``lspci -nn`` 输出，挑出**真正的算力卡**。

    关键：必须排除 QEMU/VMware 等虚拟显卡 —— 实测 目标 上 ``lspci`` 含
    ``00:01.0 VGA compatible controller: Device 1234:1111``，若按关键字
    ``vga`` 统计会把卡数算成 3 张（实测踩过的坑）。
    """
    scan = VendorScan()
    if not text or text.startswith("<error"):
        scan.error = "lspci output unavailable"
        return scan
    for line in text.splitlines():
        low = line.lower()
        if not any(h in low for h in ACCEL_CLASS_HINTS):
            continue
        m = RE_LSPCI_ACCEL.match(line.strip())
        if not m:
            continue
        vendor_id = (m.group("vendor") or "").lower()
        device_id = (m.group("device") or "").lower()
        pci_id = f"{vendor_id}:{device_id}"
        desc = _clean_desc(m.group("desc"))
        if pci_id in {d.lower() for d in denylist}:
            scan.excluded.append(f"{m.group('addr')} {desc} [{pci_id}]")
            continue
        known = vendor_id in {v.lower() for v in allowlist}
        vendor = VENDOR_NAMES.get(vendor_id, "unknown")
        if not known:
            # 未收录的厂商：记录下来但不计入算力卡（避免把显卡当算力卡）
            scan.excluded.append(f"{m.group('addr')} {desc} [{pci_id}] 非算力卡厂商")
            continue
        scan.devices.append(
            PciAccel(
                address=m.group("addr"),
                description=desc,
                vendor_id=vendor_id,
                device_id=device_id,
                vendor=vendor,
            )
        )
    seen: list[str] = []
    for d in scan.devices:
        if d.vendor not in seen:
            seen.append(d.vendor)
    scan.vendors = seen
    return scan


def has_vendor(scan: VendorScan, vendor: str) -> bool:
    """该厂家是否有卡 —— R4 条件渲染的唯一依据。"""
    return scan.count_of(vendor) > 0


def badge_text(vendor: str, model: str, count: int) -> str:
    """顶栏标识1 的算力卡摘要文案（R1）。"""
    if count <= 0:
        return "未检测到算力卡"
    display = VENDOR_DISPLAY.get(vendor, vendor.upper() if vendor else "")
    name = model or "型号未知"
    return f"{display} {name} ×{count}".strip()


def summarize(scan: VendorScan, gpu_names: list[str]) -> str:
    """多型号混插时按型号聚合，如 ``NVIDIA Tesla V100 ×1 / A100 ×1``。"""
    if not scan.devices:
        return "未检测到算力卡"
    counts: dict[str, int] = {}
    for i, d in enumerate(scan.devices):
        name = gpu_names[i] if i < len(gpu_names) else d.description
        counts[name] = counts.get(name, 0) + 1
    vendor = VENDOR_DISPLAY.get(scan.vendors[0] if scan.vendors else "", "")
    parts = [f"{n} ×{c}" for n, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    return f"{vendor} " + " / ".join(parts)


def tensor_parallel_text(enabled: bool) -> str:
    return "张量并行 开" if enabled else "张量并行 关"
