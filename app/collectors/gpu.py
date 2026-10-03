"""Collector-C：nvidia-smi 采集器（方案 TASK-06；v0.4 TASK-26 泛化）。

严格约束：
  * 单次调用取回**全部卡**字段，禁止按卡循环（开销翻倍）；
  * **卡数完全由 nvidia-smi 返回决定** —— 1 卡、2 卡、8 卡都必须正确；
  * ``fan.speed`` 照常查询：SXM2 等无风扇卡返回 ``[N/A]`` → ``None``（不显示），
    有风扇的 PCIe 卡正常显示（v0.4 F3 修复：原先恒置 None）；
  * 峰值带宽按**型号查规格表**，查不到返回 ``None``（v0.4 F2 修复：
    原先写死 900 GB/s 套用到所有卡）；
  * 子进程经 CommandRunner（异步），绝不在事件循环中同步等待；
  * [N/A] / [Not Supported] 一律转 None，不得转成 0。
"""

from __future__ import annotations

import time

from ..adapters.exec import CommandRunner
from ..config import Settings
from ..models import GpuInfo, GpuProcess
from ..services import gpu_spec
from .base import CollectorState, to_int, to_num

QUERY_FIELDS = [
    "index",
    "name",
    "uuid",
    "pci.bus_id",
    "temperature.gpu",
    "power.draw",
    "power.limit",
    "memory.total",
    "memory.used",
    "memory.free",
    "utilization.gpu",
    "utilization.memory",
    "clocks.current.graphics",
    "clocks.current.memory",
    "pcie.link.gen.current",
    "pcie.link.width.current",
    "fan.speed",
]

#: 查询字段顺序 —— 解析时按此索引取，改动上面的列表必须同步这里
IDX_FAN = QUERY_FIELDS.index("fan.speed")
#: 解析时的最小列数：兼容旧版 nvidia-smi（不返回 fan.speed）与旧夹具，
#: 此时 fan 视为 None（未知），而不是整行丢弃
MIN_FIELDS = IDX_FAN


def query_argv(nvidia_smi: str) -> list[str]:
    return [nvidia_smi, "--query-gpu=" + ",".join(QUERY_FIELDS), "--format=csv,noheader,nounits"]


def compute_argv(nvidia_smi: str) -> list[str]:
    return [
        nvidia_smi,
        "--query-compute-apps=pid,process_name,used_memory,gpu_uuid",
        "--format=csv,noheader,nounits",
    ]


def pmon_argv(nvidia_smi: str) -> list[str]:
    return [nvidia_smi, "pmon", "-c", "1"]


def parse_gpu_csv(stdout: str) -> list[GpuInfo]:
    out: list[GpuInfo] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < MIN_FIELDS:
            continue
        # 风扇：SXM2 等无风扇卡返回 [N/A] → to_int() → None（不显示）
        fan_raw = parts[IDX_FAN] if len(parts) > IDX_FAN else ""
        fan = to_int(fan_raw)
        g = GpuInfo(
            index=int(to_num(parts[0]) or 0),
            name=parts[1],
            uuid=parts[2],
            pci=parts[3],
            temp_c=to_num(parts[4]),
            power_w=to_num(parts[5]),
            power_limit_w=to_num(parts[6]),
            mem_total_mib=to_int(parts[7]),
            mem_used_mib=to_int(parts[8]),
            util_gpu_pct=to_num(parts[10]),
            util_mem_pct=to_num(parts[11]),
            clk_sm_mhz=to_int(parts[12]),
            clk_mem_mhz=to_int(parts[13]),
            pcie_gen=to_int(parts[14]),
            pcie_width=to_int(parts[15]),
            fan_pct=fan if (fan is not None and fan > 0) else None,
        )
        # 峰值带宽按**型号**查规格表；未收录型号 → None（界面显示「—」）
        g.bandwidth_gbps = gpu_spec.approx_bandwidth(g.name, g.util_mem_pct)
        g.mem_type = gpu_spec.mem_type_of(g.name)
        g.vendor = gpu_spec.vendor_of(g.name) or "unknown"
        out.append(g)
    out.sort(key=lambda g: g.index)
    return out


def parse_compute_apps(stdout: str) -> dict[str, list[GpuProcess]]:
    by_uuid: dict[str, list[GpuProcess]] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        pid = to_int(parts[0])
        if pid is None:
            continue
        proc = GpuProcess(pid=pid, name=parts[1].rsplit("/", 1)[-1], mem_mib=to_int(parts[2]))
        by_uuid.setdefault(parts[3], []).append(proc)
    return by_uuid


def parse_pmon(stdout: str) -> dict[int, dict[int, float]]:
    """nvidia-smi pmon -c 1 → {gpu_index: {pid: sm_pct}}"""
    out: dict[int, dict[int, float]] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        gi = to_int(parts[0])
        pid = to_int(parts[1])
        sm = to_num(parts[3])
        if gi is None or pid is None:
            continue
        out.setdefault(gi, {})[pid] = sm if sm is not None else 0.0
    return out


class GpuCollector:
    name = "gpu"

    def __init__(self, settings: Settings, runner: CommandRunner):
        self.s = settings
        self.runner = runner
        self.state = CollectorState(self.name, settings.stale_after_misses)
        self.gpus: list[GpuInfo] = []
        self._pmon: dict[int, dict[int, float]] = {}
        self._last_pmon_mono = 0.0

    async def collect(self) -> bool:
        t0 = time.monotonic()
        res = await self.runner.run(query_argv(self.s.nvidia_smi), label="nvidia-smi")
        if not res.ok:
            self.state.fail(res.error or f"rc={res.returncode}")
            return False
        gpus = parse_gpu_csv(res.stdout)
        if not gpus:
            self.state.fail("no gpu rows parsed")
            return False

        apps = await self.runner.run(compute_argv(self.s.nvidia_smi), label="nvidia-smi-apps")
        if apps.ok:
            by_uuid = parse_compute_apps(apps.stdout)
            for g in gpus:
                g.processes = by_uuid.get(g.uuid, [])

        now = time.monotonic()
        if now - self._last_pmon_mono >= self.s.pmon_interval_s:
            self._last_pmon_mono = now
            pm = await self.runner.run(pmon_argv(self.s.nvidia_smi), label="nvidia-smi-pmon")
            if pm.ok:
                self._pmon = parse_pmon(pm.stdout)
        for g in gpus:
            for p in g.processes:
                p.sm_pct = self._pmon.get(g.index, {}).get(p.pid)

        self.gpus = gpus
        self.state.ok((time.monotonic() - t0) * 1000.0)
        return True

    # ---- 聚合量 ----
    def vram_used_mib(self) -> int | None:
        if not self.gpus:
            return None
        vals = [g.mem_used_mib for g in self.gpus if g.mem_used_mib is not None]
        return sum(vals) if vals else None

    def vram_total_mib(self) -> int | None:
        if not self.gpus:
            return None
        vals = [g.mem_total_mib for g in self.gpus if g.mem_total_mib is not None]
        return sum(vals) if vals else None

    def max_temp_c(self) -> float | None:
        vals = [g.temp_c for g in self.gpus if g.temp_c is not None]
        return max(vals) if vals else None
