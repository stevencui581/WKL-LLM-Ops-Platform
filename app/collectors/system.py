"""Collector-F：psutil 系统采集器（方案 TASK-07）。

要点：
  * ``cpu_percent(interval=None)`` 首次返回 0，启动时预热一次并丢弃；
  * 网络吞吐用两次采样差分，首次为 None（**不是 0**）；
  * 磁盘只统计根分区（253 只有 /dev/sda4 挂在 /）。
"""

from __future__ import annotations

import time

import psutil

from ..config import Settings
from ..models import SelfInfo, SystemInfo
from .base import CollectorState

MB = 1024 * 1024


def _kb(rate_bytes_per_s: float | None) -> float | None:
    return None if rate_bytes_per_s is None else round(rate_bytes_per_s / 1024.0, 1)


#: 需要跳过的伪文件系统（v0.4 F11）
_SKIP_FSTYPES = (
    "tmpfs",
    "devtmpfs",
    "overlay",
    "squashfs",
    "snap",
    "ramfs",
    "autofs",
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "devpts",
    "fusectl",
)
_SKIP_MOUNT_PREFIX = ("/snap", "/var/snap", "/run", "/sys", "/proc", "/dev")


def _skip_fs(part) -> bool:
    """判断挂载点是否应跳过（伪文件系统 / 重复计数）。"""
    fstype = (getattr(part, "fstype", "") or "").lower()
    if fstype in _SKIP_FSTYPES or fstype.startswith("fuse."):
        return True
    mp = getattr(part, "mountpoint", "") or ""
    if not mp:
        return True
    return any(mp == p or mp.startswith(p + "/") for p in _SKIP_MOUNT_PREFIX)


class SystemCollector:
    name = "system"

    def __init__(self, settings: Settings):
        self.s = settings
        self.state = CollectorState(self.name, settings.stale_after_misses)
        self.info = SystemInfo()
        self._last_net = None
        self._last_net_mono: float | None = None
        self._proc = psutil.Process()
        self._start_mono = time.monotonic()

    def warmup(self) -> None:
        """预热 CPU 采样与网络基线，避免首帧出现 0% / None。"""
        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None, percpu=True)
            self._last_net = psutil.net_io_counters()
            self._last_net_mono = time.monotonic()
        except Exception:  # noqa: BLE001 - 预热失败不影响主流程
            pass

    def collect(self) -> bool:
        t0 = time.monotonic()
        try:
            info = SystemInfo()
            info.cpu_pct = psutil.cpu_percent(interval=None)
            info.cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            try:
                l1, l5, l15 = psutil.getloadavg()
                info.load1, info.load5, info.load15 = l1, l5, l15
            except (AttributeError, OSError):
                pass
            vm = psutil.virtual_memory()
            info.mem_total_mb = int(vm.total / MB)
            info.mem_used_mb = int((vm.total - vm.available) / MB)
            info.mem_pct = float(vm.percent)
            sm = psutil.swap_memory()
            info.swap_total_mb = int(sm.total / MB)
            info.swap_used_mb = int(sm.used / MB)
            # v0.4 F11：统计**所有真实挂载点**，不再只看 "/"。
            # 过滤伪文件系统（tmpfs/overlay/squashfs/snap 等）。
            #
            # 关键：必须按**设备**去重！systemd 的 ProtectSystem=strict 与
            # ReadWritePaths 会为服务创建若干 bind mount，它们指向 /dev/sda4
            # 的不同目录，`disk_usage()` 会各自返回同一块盘的容量。
            # 实测不去重时容量被重复累加 **7 倍**（283.8 GiB → 1983.9 GB）。
            per_device: dict[str, tuple[int, int]] = {}
            for part in psutil.disk_partitions(all=False):
                if _skip_fs(part):
                    continue
                key = part.device or part.mountpoint
                if key in per_device:
                    continue  # 同一设备的 bind mount，容量只算一次
                try:
                    du = psutil.disk_usage(part.mountpoint)
                except (OSError, PermissionError):
                    continue
                per_device[key] = (du.total, du.used)
            if per_device:
                total = sum(t for t, _ in per_device.values())
                used = sum(u for _, u in per_device.values())
            else:  # 兜底：至少给根分区
                du = psutil.disk_usage("/")
                total, used = du.total, du.used
            info.disk_total_gb = round(total / (1024**3), 1)
            info.disk_used_gb = round(used / (1024**3), 1)
            info.disk_pct = round(used / total * 100.0, 1) if total else None

            net = psutil.net_io_counters()
            now = time.monotonic()
            if self._last_net is not None and self._last_net_mono is not None:
                dt = now - self._last_net_mono
                if dt > 0:
                    info.net_rx_kbps = _kb((net.bytes_recv - self._last_net.bytes_recv) / dt)
                    info.net_tx_kbps = _kb((net.bytes_sent - self._last_net.bytes_sent) / dt)
            self._last_net = net
            self._last_net_mono = now

            self.info = info
            self.state.ok((time.monotonic() - t0) * 1000.0)
            return True
        except Exception as exc:  # noqa: BLE001
            self.state.fail(f"{type(exc).__name__}: {exc}")
            return False

    def self_info(self, ws_clients: int = 0) -> SelfInfo:
        """控制台自身开销（TASK-21）。"""
        out = SelfInfo(ws_clients=ws_clients, uptime_s=round(time.monotonic() - self._start_mono, 1))
        try:
            with self._proc.oneshot():
                out.cpu_pct = round(self._proc.cpu_percent(interval=None), 2)
                out.rss_mb = round(self._proc.memory_info().rss / MB, 1)
                out.threads = self._proc.num_threads()
        except Exception:  # noqa: BLE001
            pass
        return out
