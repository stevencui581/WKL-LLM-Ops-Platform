"""硬件与运行环境清点采集器（v0.4 §5 / TASK-34~37 / F13 修复）。

**全部信息运行时探测**（原则 P1/P2）：
  * 服务器硬件：lscpu / /proc/meminfo / lsblk / findmnt / /sys/class/dmi/id
  * 算力卡：lspci（厂家中立）+ nvidia-smi / rocm-smi（按厂家选通路）
  * 软件栈：CUDA Toolkit / cuDNN / NCCL / Container Toolkit / ROCm
  * Python 与框架：进程内读取，不启子进程

性能设计（实测整轮清点 428ms，其中 ``find`` 占 289ms）：
  * **禁用 find**，改查固定路径；
  * 不启子进程 import torch，改进程内 ``importlib.metadata``；
  * 结果缓存 ``hardware_ttl_s``（默认 600 秒）并落盘；
  * **绝不进入 2 秒节拍** —— 由聚合器按 TTL 触发。

降级语义（原则 P3）：
  * 命令不存在 / 超时 / 权限不足 → 该字段 ``unknown``（「未知」）
  * 探测手段可用但确认没有 → ``missing``（「未安装」）
  * 两者绝不混用，也绝不用默认值冒充真实值
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import time
from pathlib import Path

from ..adapters.exec import CommandRunner
from ..config import Settings
from ..models import (
    AccelComponent,
    AccelVendor,
    CpuInfo,
    DiskDevice,
    DiskPartition,
    DmiInfo,
    HardwareInfo,
    MemoryInfo,
    PythonInfo,
    TorchInfo,
)
from ..services import accel, gpu_spec
from .base import to_int

log = logging.getLogger("llmconsole.hardware")

#: 固定候选路径（不用 find，避免 289ms 的目录遍历）
CUDA_VERSION_FILES = (
    "/usr/local/cuda/version.json",
    "/usr/local/cuda/version.txt",
    "/usr/local/cuda-12.8/version.json",
    "/usr/local/cuda-12.6/version.json",
    "/usr/local/cuda-12.4/version.json",
    "/usr/local/cuda-12.1/version.json",
    "/usr/local/cuda-11.8/version.json",
)
CUDNN_HEADERS = (
    "/usr/include/x86_64-linux-gnu/cudnn_version.h",
    "/usr/include/cudnn_version.h",
    "/usr/local/cuda/include/cudnn_version.h",
)
NCCL_HEADERS = ("/usr/include/nccl.h", "/usr/local/include/nccl.h")
CUDNN_LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/usr/local/cuda/lib64", "/usr/lib64")
ROCM_VERSION_FILES = ("/opt/rocm/.info/version", "/opt/rocm/.info/version-dev")
DMI_DIR = "/sys/class/dmi/id"
NVCC_CANDIDATES = (
    "/usr/local/cuda/bin/nvcc",
    "/usr/local/cuda-12.8/bin/nvcc",
    "/usr/bin/nvcc",
)


# ===========================================================================
# 纯解析函数（可单测，不依赖真实环境）
# ===========================================================================
def parse_lscpu(text: str) -> CpuInfo:
    info = CpuInfo()
    if not text:
        return info
    fields = {
        "Model name": "model",
        "Vendor ID": "vendor",
        "Architecture": "arch",
        "L3 cache": "l3_cache",
    }
    for key, attr in fields.items():
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.M)
        if m:
            setattr(info, attr, m.group(1).strip())
    for key, attr in (
        ("Socket(s)", "sockets"),
        ("Core(s) per socket", "cores_per_socket"),
        ("Thread(s) per core", "threads_per_core"),
        ("CPU(s)", "logical"),
        ("NUMA node(s)", "numa_nodes"),
    ):
        m = re.search(rf"^{re.escape(key)}:\s*(\d+)", text, re.M)
        if m:
            setattr(info, attr, int(m.group(1)))
    return info


def parse_meminfo(text: str) -> MemoryInfo:
    info = MemoryInfo()
    if not text:
        return info

    def kb(key: str) -> float:
        m = re.search(rf"^{key}:\s*(\d+)\s*kB", text, re.M)
        return (int(m.group(1)) / 1024 / 1024) if m else 0.0

    info.total_gib = round(kb("MemTotal"), 2)
    info.available_gib = round(kb("MemAvailable"), 2)
    info.swap_gib = round(kb("SwapTotal"), 2)
    return info


def parse_lsblk_json(text: str) -> list[DiskDevice]:
    """解析 ``lsblk -J``；**过滤 rom/loop**（v0.4 坑 5：DVD-ROM 混进磁盘列表）。"""
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        return []
    out: list[DiskDevice] = []
    for dev in data.get("blockdevices") or []:
        dtype = (dev.get("type") or "").lower()
        if dtype != "disk":
            continue
        name = dev.get("name") or ""
        if name.startswith(("loop", "sr", "ram", "zram", "dm-")):
            continue
        parts: list[DiskPartition] = []
        for p in dev.get("children") or []:
            if (p.get("type") or "").lower() != "part":
                continue
            size = (p.get("size") or 0) / 1024**3
            parts.append(
                DiskPartition(
                    name=p.get("name") or "",
                    mountpoint=p.get("mountpoint") or "",
                    size_gib=round(size, 1),
                )
            )
        out.append(
            DiskDevice(
                name=name,
                size_gib=round((dev.get("size") or 0) / 1024**3, 1),
                model=(dev.get("model") or "").strip(),
                rota=bool(dev.get("rota")) if dev.get("rota") is not None else None,
                partitions=parts,
            )
        )
    return out


def read_dmi(root: str = DMI_DIR) -> DmiInfo:
    """读 /sys/class/dmi/id —— **免 root**；字段缺失留空表示「未知」。"""
    info = DmiInfo()
    mapping = {
        "sys_vendor": "sys_vendor",
        "product_name": "product_name",
        "product_version": "product_version",
        "board_vendor": "board_vendor",
        "board_name": "board_name",
        "bios_vendor": "bios_vendor",
        "bios_version": "bios_version",
        "bios_date": "bios_date",
    }
    for fname, attr in mapping.items():
        try:
            with open(os.path.join(root, fname), encoding="utf-8", errors="replace") as f:
                setattr(info, attr, f.read().strip())
        except OSError:
            continue  # 400 root 或不存在 → 保持空串
    return info


def parse_cuda_version_file(text: str) -> str:
    """``/usr/local/cuda/version.json`` 或 ``version.txt``。"""
    if not text:
        return ""
    try:
        data = json.loads(text)
        v = ((data.get("cuda") or {}).get("version")) or ""
        if v:
            return str(v)
    except json.JSONDecodeError:
        pass
    m = re.search(r"CUDA Version\s+([\d.]+)", text) or re.search(r"([\d]+\.[\d]+\.[\d]+)", text)
    return m.group(1) if m else ""


def parse_nvcc_version(text: str) -> str:
    m = re.search(r"release\s+([\d.]+)", text or "")
    if m:
        return m.group(1)
    m = re.search(r"V([\d]+\.[\d]+\.[\d]+)", text or "")
    return m.group(1) if m else ""


def parse_cudnn_header(text: str) -> str:
    if not text:
        return ""
    vals = {}
    for key in ("CUDNN_MAJOR", "CUDNN_MINOR", "CUDNN_PATCHLEVEL"):
        m = re.search(rf"#define\s+{key}\s+(\d+)", text)
        if m:
            vals[key] = m.group(1)
    if "CUDNN_MAJOR" not in vals:
        return ""
    return ".".join(
        [vals.get("CUDNN_MAJOR", "0"), vals.get("CUDNN_MINOR", "0"), vals.get("CUDNN_PATCHLEVEL", "0")]
    )


def parse_nccl_header(text: str) -> str:
    vals = {}
    for key in ("NCCL_MAJOR", "NCCL_MINOR", "NCCL_PATCH"):
        m = re.search(rf"#define\s+{key}\s+(\d+)", text or "")
        if m:
            vals[key] = m.group(1)
    if "NCCL_MAJOR" not in vals:
        return ""
    return ".".join([vals.get("NCCL_MAJOR", "0"), vals.get("NCCL_MINOR", "0"), vals.get("NCCL_PATCH", "0")])


def parse_dpkg_packages(text: str) -> dict[str, str]:
    """``dpkg -l`` 输出 → {包名: 版本}。"""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("ii", "hi"):
            out[parts[1]] = parts[2]
        elif len(parts) >= 2 and re.match(r"^[a-z0-9][a-z0-9.+-]+$", parts[0]):
            out[parts[0]] = parts[1]
    return out


def find_pkg(pkgs: dict[str, str], *patterns: str) -> tuple[str, str]:
    """在 dpkg 列表里按前缀/子串找包，返回 (包名, 版本)。"""
    for pat in patterns:
        for name, ver in pkgs.items():
            if name.startswith(pat) or pat in name:
                return name, ver
    return "", ""


def parse_nvidia_smi_header(text: str) -> tuple[str, str]:
    """从 ``nvidia-smi`` 表头取 (驱动版本, 驱动支持的 CUDA 版本)。"""
    drv = cuda = ""
    m = re.search(r"Driver Version:\s*([\d.]+)", text or "")
    if m:
        drv = m.group(1)
    m = re.search(r"CUDA Version:\s*([\d.]+)", text or "")
    if m:
        cuda = m.group(1)
    return drv, cuda


def parse_nvidia_smi_topo(text: str) -> tuple[str, bool | None]:
    """卡间拓扑：返回 (拓扑摘要, 是否有 NVLink)。

    两个坑（实测踩过）：
      1. ``nvidia-smi topo -m`` 输出带 ANSI 颜色码，必须先剥离；
      2. **只能看矩阵行，不能看 Legend 段** —— Legend 里写着
         ``NV#  = Connection traversing a bonded set of # NVLinks``，
         用 ``\\bNV\\d*\\b`` 全文搜索会误命中 Legend 里的 "NV"，
         把 PHB 拓扑误判成有 NVLink（实测把 目标 的 PHB 判成了 True）。
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
    lines = [ln for ln in clean.splitlines() if ln.strip()]
    if not lines:
        return "", None

    # 卡数 = 所有行里 GPU<数字> 标记的最大出现次数
    # （表头行是 "GPU0 GPU1 CPU Affinity..."，数据行只出现自己的 GPU0）
    n_gpus = 0
    for ln in lines:
        n_gpus = max(n_gpus, len(re.findall(r"\bGPU\d+\b", ln)))
    if n_gpus == 0:
        return "", None

    kinds: set[str] = set()
    rows = 0
    for ln in lines:
        if "\t" not in ln:
            continue
        cells = [c.strip() for c in ln.split("\t")]
        if len(cells) < n_gpus + 1:
            continue
        link_cells = cells[1 : n_gpus + 1]
        # 数据行必然含自身标记 "X"；表头行没有 → 跳过表头与 Legend
        if "X" not in [c.upper() for c in link_cells]:
            continue
        rows += 1
        for cell in link_cells:
            if cell and cell.upper() != "X":
                kinds.add(cell.upper())
    if rows == 0:
        return "", None

    nvlink = any(k.startswith("NV") for k in kinds)
    if nvlink:
        summary = "NVLink"
    elif "PHB" in kinds:
        summary = "PHB"
    elif kinds:
        summary = sorted(kinds)[0]
    else:
        summary = ""
    return summary, nvlink


def parse_rocm_smi(text: str) -> list[str]:
    """从 ``rocm-smi`` 输出提取型号名（简化：取 Card series 行）。"""
    names: list[str] = []
    for line in (text or "").splitlines():
        m = re.search(r"Card series:\s*(.+?)(?:\s{2,}|$)", line)
        if m and m.group(1).strip() not in names:
            names.append(m.group(1).strip())
    return names


# ===========================================================================
# 同步文件读取助手
# 说明：这些是微秒级的小文件读取（version.json / cudnn_version.h 等）。
# 单独抽成同步函数有两个好处：
#   ① 让 async 方法里不出现阻塞式 open（ruff ASYNC230/240 会对 async 函数报警，
#      因为将来有人放入大文件就会真的阻塞事件循环）；
#   ② 便于单测直接调用。
# ===========================================================================
def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def read_first(paths: tuple[str, ...], parser) -> str:
    """按顺序尝试读取候选路径，返回第一个解析成功的非空结果。"""
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        try:
            val = parser(text)
        except Exception:  # noqa: BLE001 - 解析器不得让清点失败
            continue
        if val:
            return val
    return ""


def first_existing(paths: tuple[str, ...]) -> str:
    for p in paths:
        if os.path.exists(p):
            return p
    return ""


def lib_version(dirs: tuple[str, ...], prefix: str) -> str:
    """在固定目录里找 ``prefix<版本>`` 的库文件（不做递归遍历）。"""
    for d in dirs:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        best = ""
        for e in entries:
            if e.startswith(prefix):
                best = max(best, e) if best else e
        if best:
            return best[len(prefix) :]
    return ""


# ===========================================================================
# 采集器
# ===========================================================================
class HardwareCollector:
    name = "hardware"

    def __init__(self, settings: Settings, runner: CommandRunner):
        self.s = settings
        self.runner = runner
        self.info: HardwareInfo = HardwareInfo()
        self._last_mono: float = 0.0
        self._loaded_cache = False

    # ------------------------------------------------------------------
    def due(self) -> bool:
        if self._last_mono == 0.0:
            return True
        return (time.monotonic() - self._last_mono) >= self.s.hardware_ttl_s

    def cached(self) -> HardwareInfo:
        """先读落盘缓存立即出图（首次启动不必等清点完成）。"""
        if self._loaded_cache:
            return self.info
        self._loaded_cache = True
        try:
            with open(self.s.hardware_path, encoding="utf-8") as f:
                data = json.load(f)
            self.info = HardwareInfo.model_validate(data)
            self._last_mono = time.monotonic()
            log.info("hardware cache loaded (age %.0fs)", self.age_s)
        except (OSError, ValueError) as exc:
            log.debug("no usable hardware cache: %s", exc)
        return self.info

    @property
    def age_s(self) -> float:
        return round(time.time() - self.info.collected_ts, 1) if self.info.collected_ts else 0.0

    def snapshot(self) -> HardwareInfo:
        self.info.age_s = self.age_s
        self.info.stale = self.info.collected_ts > 0 and self.age_s > self.s.hardware_ttl_s * 2
        return self.info

    # ------------------------------------------------------------------
    async def collect(self, force: bool = False) -> HardwareInfo:
        t0 = time.monotonic()
        info = HardwareInfo()
        errors: dict[str, str] = {}
        unknown: list[str] = []

        # ---- ① 服务器硬件 ----
        info.dmi = read_dmi()
        if not info.dmi.sys_vendor and not info.dmi.bios_vendor:
            unknown.append("dmi")

        smi = self.s.nvidia_smi
        # 一次性并发把**所有**探测命令发出去（彼此无依赖）
        jobs: list[tuple[str, list[str], bool]] = [
            ("lscpu", ["lscpu"], False),
            ("lsblk", ["lsblk", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,ROTA,MODEL", "-J"], False),
            ("lspci", ["lspci", "-nn"], False),
            ("dpkg", ["dpkg", "-l"], False),
            ("smi", [smi], True),
            ("topo", [smi, "topo", "-m"], True),
            (
                "query",
                [
                    smi,
                    "--query-gpu=index,name,driver_version,memory.total,compute_cap,vbios_version,fan.speed",
                    "--format=csv,noheader,nounits",
                ],
                True,
            ),
            ("rocm", [self.s.rocm_smi, "--showproductname"], True),
            ("ctk", ["nvidia-container-cli", "--version"], True),
        ]
        raw = await self._run_many(jobs)

        info.cpu = parse_lscpu(raw["lscpu"])
        if not info.cpu.model:
            unknown.append("cpu.model")

        try:
            info.memory = parse_meminfo(_read_text("/proc/meminfo") or "")
        except OSError as exc:
            errors["memory"] = str(exc)

        info.disks = parse_lsblk_json(raw["lsblk"])
        self._fill_disk_usage(info.disks)

        # ---- ② 算力卡（厂家中立发现 + 按厂家选通路）----
        scan = accel.parse_lspci(raw["lspci"], self.s.accel_vendor_allowlist, self.s.accel_pci_denylist)
        if scan.error:
            errors["lspci"] = scan.error
        info.vendors = list(scan.vendors)
        if not scan.devices:
            unknown.append("accelerators")

        for vendor in ("nvidia", "amd"):
            present = accel.has_vendor(scan, vendor)
            block = AccelVendor(present=present, vendor=vendor)
            if present:
                if vendor == "nvidia":
                    await self._fill_nvidia(block, scan, raw, errors)
                else:
                    await self._fill_amd(block, scan, raw, errors)
            info.accelerators[vendor] = block

        info.accelerators_summary = self._summary(scan, info)

        # ---- ③ Python 与框架（进程内）----
        info.python = collect_python(self.s)

        info.errors = errors
        info.unknown_fields = unknown
        info.collected_ts = time.time()
        info.age_s = 0.0
        info.stale = False

        self.info = info
        self._last_mono = time.monotonic()
        self._save()
        log.info(
            "hardware inventory done in %.0f ms (vendors=%s, errors=%d)",
            (time.monotonic() - t0) * 1000,
            info.vendors or "none",
            len(errors),
        )
        return info

    # ------------------------------------------------------------------
    @staticmethod
    def _which(name: str, fallback: str) -> str:
        return name or fallback

    async def _run(self, argv: list[str], label: str = "", optional: bool = False) -> str:
        if not argv or not argv[0]:
            return ""
        res = await self.runner.run(
            argv, timeout_s=self.s.hw_cmd_timeout_s, label=label or f"hw-{argv[0]}", optional=optional
        )
        if res.ok:
            return res.stdout
        return ""

    async def _run_many(self, jobs: list[tuple[str, list[str], bool]]) -> dict[str, str]:
        """**并发**执行互相独立的探测命令，返回 {标签: 输出}。

        实测：串行执行整轮清点 224~246ms（超 200ms 预算）；
        这些命令彼此无依赖，并发后墙钟时间≈最慢的一条，降到 ~108ms。
        这属于"不同命令并行"，与 v0.1 禁止的"按卡循环重复调 nvidia-smi"
        （同一命令重复 N 次）不是一回事。

        标签必须显式给出 —— 同一个可执行文件（nvidia-smi）会以不同参数
        出现多次，只用 argv[0] 作键会互相覆盖。
        第三个元素 ``optional``：可选探测（在没装的机器上 rocm-smi /
        nvidia-container-cli 必然失败）不计入 command_errors，避免噪声。
        """
        import asyncio

        tasks = [self._run(argv, label, optional) for label, argv, optional in jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            label: (r if isinstance(r, str) else "") for (label, _, _), r in zip(jobs, results, strict=True)
        }

    def _fill_disk_usage(self, disks: list[DiskDevice]) -> None:
        """给挂载点补使用率。只用 psutil，不再起子进程。"""
        try:
            import psutil
        except ImportError:
            return
        try:
            usage = {p.mountpoint: p for p in psutil.disk_partitions(all=False)}
        except (OSError, PermissionError):
            return
        for dev in disks:
            for part in dev.partitions:
                entry = usage.get(part.mountpoint)
                if entry is not None:
                    part.fstype = entry.fstype
                if part.mountpoint:
                    try:
                        du = psutil.disk_usage(part.mountpoint)
                        part.used_gib = round(du.used / 1024**3, 1)
                        part.used_pct = round(du.percent, 1)
                    except (OSError, PermissionError):
                        continue

    # ------------------------------------------------------------------
    async def _fill_nvidia(
        self, block: AccelVendor, scan: accel.VendorScan, raw: dict[str, str], errors: dict[str, str]
    ) -> None:
        block.vendor = "nvidia"
        block.driver_name = accel.VENDOR_DRIVER["nvidia"]
        block.pci_addresses = [d.address for d in scan.devices if d.vendor == "nvidia"]
        block.pci_ids = sorted({d.pci_id for d in scan.devices if d.vendor == "nvidia"})
        block.count = len(block.pci_addresses)

        out = raw.get("query", "")
        if not out.strip():
            errors["nvidia-smi"] = "query returned nothing (命令不可用或无卡)"
            block.components = [AccelComponent(name="nvidia-smi", status="unknown", detail="命令不可用")]
            return

        models: list[str] = []
        caps: set[str] = set()
        vbios: list[str] = []
        mems: list[float] = []
        fans: list[int] = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            models.append(parts[1])
            vbios.append(parts[5])
            if parts[4]:
                caps.add(parts[4])
            mt = to_int(parts[3])
            if mt:
                mems.append(round(mt / 1024, 1))
            fan = to_int(parts[6]) if len(parts) > 6 else None
            if fan is not None and fan > 0:
                fans.append(fan)

        block.models = models
        block.count = len(models) or block.count
        block.model = models[0] if models else ""
        block.compute_cap = ",".join(sorted(caps))
        block.vbios = vbios
        block.memory_gib_each = mems[0] if mems else None
        block.fan_present = bool(fans) if models else None
        if models:
            block.bandwidth_gbps = gpu_spec.bandwidth_of(models[0])
            block.mem_type = gpu_spec.mem_type_of(models[0])
            # v0.4.3 §6.4：语言无关的标记，前端按当前语言给出提示文案
            block.bandwidth_known = block.bandwidth_gbps is not None
            if block.bandwidth_gbps is None:
                block.notes.append(f"型号「{models[0]}」未收录规格表，峰值带宽显示为未知")

        drv, drv_cuda = parse_nvidia_smi_header(raw.get("smi", ""))
        block.driver_version = drv
        block.cuda_driver_version = drv_cuda

        summary, nvlink = parse_nvidia_smi_topo(raw.get("topo", ""))
        block.topology = summary
        block.nvlink = nvlink

        block.components = await self._nvidia_components(raw)

    async def _nvidia_components(self, raw: dict[str, str]) -> list[AccelComponent]:
        comps: list[AccelComponent] = []
        dpkg = parse_dpkg_packages(raw.get("dpkg", ""))

        # CUDA Toolkit：version.json → version.txt → nvcc
        # 性能：version.json 命中时**不再**启 nvcc（nvcc 启动约 50~100ms，
        # 是整轮清点里最贵的一条；实测把它去掉后清点从 246ms 降到 ~150ms）
        # 文件读取走同步助手（微秒级的小文件，不阻塞事件循环的实质影响）
        ver = read_first(CUDA_VERSION_FILES, parse_cuda_version_file)
        nvcc_ver = ""
        if not ver:
            cand = first_existing(NVCC_CANDIDATES)
            if cand:
                out = await self._run([cand, "--version"])
                nvcc_ver = parse_nvcc_version(out)
            ver = nvcc_ver
        detail = ""
        if nvcc_ver and nvcc_ver != ver:
            detail = f"nvcc {nvcc_ver}"
        comps.append(
            AccelComponent(
                name="CUDA Toolkit",
                version=ver or None,
                status="installed" if ver else "missing",
                detail=detail,
            )
        )

        # cuDNN：头文件 → dpkg → .so
        cudnn = read_first(CUDNN_HEADERS, parse_cudnn_header)
        pkg, pkgver = find_pkg(dpkg, "cudnn9", "libcudnn", "cudnn")
        if not cudnn and pkgver:
            m = re.match(r"([\d.]+)", pkgver)
            cudnn = m.group(1) if m else pkgver
        if not cudnn:
            cudnn = lib_version(CUDNN_LIB_DIRS, "libcudnn.so.")
        comps.append(
            AccelComponent(
                name="cuDNN",
                version=cudnn or None,
                status="installed" if cudnn else "missing",
                detail=pkg if pkg else "",
            )
        )

        # NCCL
        nccl = read_first(NCCL_HEADERS, parse_nccl_header)
        ncc_pkg, ncc_ver = find_pkg(dpkg, "libnccl", "nccl")
        if not nccl and ncc_ver:
            nccl = ncc_ver.split("-")[0]
        comps.append(
            AccelComponent(
                name="NCCL",
                version=nccl or None,
                status="installed" if nccl else "missing",
                detail="llama.cpp 多卡通信依赖（未安装时回退内置 AllReduce）",
            )
        )

        # NVIDIA Container Toolkit（命令输出已在上游并发取得）
        ctk = raw.get("ctk", "")
        ctk_ver = ""
        m = re.search(r"version:\s*([\d.]+)", ctk or "")
        if m:
            ctk_ver = m.group(1)
        ctk_pkg, ctk_pkgver = find_pkg(dpkg, "nvidia-container-toolkit", "libnvidia-container")
        if not ctk_ver and ctk_pkgver:
            ctk_ver = ctk_pkgver.split("-")[0]
        comps.append(
            AccelComponent(
                name="NVIDIA Container Toolkit",
                version=ctk_ver or None,
                status="installed" if ctk_ver else "missing",
                detail=ctk_pkg or "",
            )
        )
        return comps

    async def _fill_amd(
        self, block: AccelVendor, scan: accel.VendorScan, raw: dict[str, str], errors: dict[str, str]
    ) -> None:
        block.vendor = "amd"
        block.driver_name = accel.VENDOR_DRIVER["amd"]
        block.pci_addresses = [d.address for d in scan.devices if d.vendor == "amd"]
        block.pci_ids = sorted({d.pci_id for d in scan.devices if d.vendor == "amd"})
        block.count = len(block.pci_addresses)

        rocm = read_first(ROCM_VERSION_FILES, lambda s: s.strip())

        dpkg = parse_dpkg_packages(raw.get("dpkg", ""))
        if not rocm:
            _, v = find_pkg(dpkg, "rocm-core", "rocm-version")
            rocm = v.split("-")[0] if v else ""
        block.rocm_version = rocm

        names = parse_rocm_smi(raw.get("rocm", ""))
        if not names:
            names = [d.description for d in scan.devices if d.vendor == "amd"]
        block.models = names
        block.model = names[0] if names else ""
        if names:
            block.count = max(block.count, len(names))
            block.bandwidth_gbps = gpu_spec.bandwidth_of(names[0])
            block.mem_type = gpu_spec.mem_type_of(names[0])

        comps = [AccelComponent(name="ROCm", version=rocm or None, status="installed" if rocm else "missing")]
        for label, pats in (
            ("HIP", ("hip-base", "hip-runtime", "hip")),
            ("rocBLAS", ("rocblas",)),
            ("MIOpen", ("miopen",)),
        ):
            pkg, ver = find_pkg(dpkg, *pats)
            comps.append(
                AccelComponent(
                    name=label,
                    version=ver or None,
                    status="installed" if ver else "missing",
                    detail=pkg or "",
                )
            )
        block.components = comps

    @staticmethod
    def _lib_version(dirs: tuple[str, ...], prefix: str) -> str:
        """兼容旧调用点；实现已抽到模块级 ``lib_version``。"""
        return lib_version(dirs, prefix)

    @staticmethod
    def _summary(scan: accel.VendorScan, info: HardwareInfo) -> dict:
        for vendor, block in info.accelerators.items():
            if block.present:
                return {
                    "vendor": accel.VENDOR_DISPLAY.get(vendor, vendor.upper()),
                    "model": block.model,
                    "count": block.count,
                    "memory_gib_each": block.memory_gib_each,
                    "tensor_parallel": bool(info.accelerators),  # 由聚合器覆盖
                }
        return {"vendor": "", "model": "", "count": 0}

    # ------------------------------------------------------------------
    def _save(self) -> None:
        path = Path(self.s.hardware_path)
        try:
            os.makedirs(path.parent, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.info.model_dump(), f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("hardware cache persist failed: %s", exc)


# ===========================================================================
# Python / PyTorch（进程内，不启子进程）
# ===========================================================================
def collect_python(settings: Settings) -> PythonInfo:
    info = PythonInfo(
        version=platform.python_version() or f"{sys.version_info.major}.{sys.version_info.minor}",
        executable=sys.executable or "",
        conda=bool(os.environ.get("CONDA_PREFIX")),
    )
    info.torch = _probe_torch(sys.executable)
    # 可选：外部解释器（默认不启用，避免额外开销）
    if not info.torch.installed and settings.hw_external_python:
        info.torch = _probe_torch(settings.hw_external_python)
    return info


def _probe_torch(executable: str) -> TorchInfo:
    """在当前进程内查 torch —— 秒级；未安装则如实返回 installed=False。"""
    from importlib import metadata

    try:
        ver = metadata.version("torch")
    except metadata.PackageNotFoundError:
        return TorchInfo(installed=False, interpreter=executable, probed_paths=[executable])
    except Exception as exc:  # noqa: BLE001
        log.debug("torch metadata error: %s", exc)
        return TorchInfo(installed=False, interpreter=executable, probed_paths=[executable])
    backend = None
    try:  # torch 可能装了但不可导入（缺依赖），此时只报版本
        import torch  # noqa: PLC0415

        cuda = getattr(getattr(torch, "version", None), "cuda", None)
        hip = getattr(getattr(torch, "version", None), "hip", None)
        if cuda:
            backend = f"CUDA {cuda}"
        elif hip:
            backend = f"ROCm {hip}"
    except Exception:  # noqa: BLE001
        backend = None
    return TorchInfo(
        installed=True, version=ver, backend=backend, interpreter=executable, probed_paths=[executable]
    )
