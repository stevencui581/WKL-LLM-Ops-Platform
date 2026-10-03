"""系统采集器测试（v0.4 F11：多挂载点统计 + 设备去重）。

背景（实测踩过的坑）：
    systemd 的 ``ProtectSystem=strict`` 与 ``ReadWritePaths`` 会为服务创建
    若干 bind mount，它们指向同一块设备（/dev/sda4）的不同目录。
    ``psutil.disk_partitions()`` 会把这些挂载点都列出来，而
    ``psutil.disk_usage()`` 对每个挂载点都返回**同一块盘**的容量。
    若简单累加，容量会被重复计算 —— 实测重复了 **7 倍**
    （真实 283.8 GiB 被算成 1983.9 GB）。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.collectors.system import _skip_fs


def _part(device: str, mountpoint: str, fstype: str = "xfs"):
    return SimpleNamespace(device=device, mountpoint=mountpoint, fstype=fstype)


# ---------------------------------------------------------------- 过滤规则
def test_skip_pseudo_filesystems():
    for fs in ("tmpfs", "devtmpfs", "overlay", "squashfs", "snap", "proc", "sysfs"):
        assert _skip_fs(_part("none", "/mnt/x", fs)) is True, fs
    assert _skip_fs(_part("none", "/mnt/x", "fuse.gvfsd-fuse")) is True


def test_skip_system_mountpoints():
    for mp in ("/snap/core/1", "/var/snap/x", "/run/user/0", "/sys/kernel", "/proc/1", "/dev/shm"):
        assert _skip_fs(_part("/dev/sda4", mp)) is True, mp


def test_keep_real_filesystems():
    assert _skip_fs(_part("/dev/sda4", "/", "xfs")) is False
    assert _skip_fs(_part("/dev/sda2", "/boot", "xfs")) is False
    assert _skip_fs(_part("/dev/nvme0n1p1", "/data", "ext4")) is False


# ---------------------------------------------------------------- 去重逻辑
class _FakePsutil:
    """模拟 systemd 沙箱里的挂载视图：同一设备出现多次（bind mount）。"""

    def __init__(self, parts, usage):
        self._parts = parts
        self._usage = usage

    def disk_partitions(self, all=False):  # noqa: A002 - 与 psutil 签名一致
        return self._parts

    def disk_usage(self, mountpoint):
        return self._usage[mountpoint]

    # 其余方法供 SystemCollector 调用
    def cpu_percent(self, interval=None, percpu=False):
        return [0.0] if percpu else 0.0

    def getloadavg(self):
        return (0.1, 0.2, 0.3)

    def virtual_memory(self):
        return SimpleNamespace(total=1 << 30, available=1 << 29, percent=50.0)

    def swap_memory(self):
        return SimpleNamespace(total=1 << 30, used=0)

    def net_io_counters(self):
        return SimpleNamespace(bytes_recv=0, bytes_sent=0)

    def Process(self):  # noqa: N802 - 与 psutil 命名一致
        return SimpleNamespace(
            cpu_percent=lambda interval=None: 1.0,
            memory_info=lambda: SimpleNamespace(rss=64 * 1024 * 1024),
            num_threads=lambda: 5,
            create_time=lambda: 0.0,
            oneshot=lambda: _NullCtx(),
        )


class _NullCtx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def _collect_with(monkeypatch, fake) -> object:
    import app.collectors.system as sysmod

    monkeypatch.setattr(sysmod, "psutil", fake)
    from app.config import Settings

    c = sysmod.SystemCollector(Settings())
    assert c.collect() is True
    return c.info


def test_bind_mounts_do_not_inflate_disk_total(monkeypatch):
    """回归：同一设备的多个 bind mount 只能计一次容量（实测曾重复 7 倍）。"""
    dev = "/dev/sda4"
    # 真实的挂载 + 6 个由沙箱产生的 bind mount（同设备）
    parts = [_part(dev, "/"), _part("/dev/sda2", "/boot", "xfs")]
    parts += [_part(dev, f"/run/systemd/unit-{i}") for i in range(6)]
    usage = {
        "/": SimpleNamespace(total=300 * 1024**3, used=177 * 1024**3, percent=59.0),
        "/boot": SimpleNamespace(total=512 * 1024**2, used=256 * 1024**2, percent=50.0),
    }
    usage.update({f"/run/systemd/unit-{i}": usage["/"] for i in range(6)})
    info = _collect_with(monkeypatch, _FakePsutil(parts, usage))

    expect_gib = (300 * 1024**3 + 512 * 1024**2) / 1024**3
    assert abs(info.disk_total_gb - round(expect_gib, 1)) < 0.2, (
        f"容量被重复累加：得到 {info.disk_total_gb} GiB，期望 {round(expect_gib, 1)} GiB"
    )
    assert info.disk_pct < 70, "占用率不应因重复累加而失真"


def test_zero_partitions_falls_back_to_root(monkeypatch):
    usage = {"/": SimpleNamespace(total=100 * 1024**3, used=50 * 1024**3, percent=50.0)}
    info = _collect_with(monkeypatch, _FakePsutil([], usage))
    assert info.disk_total_gb == 100.0
    assert info.disk_used_gb == 50.0
    assert info.disk_pct == 50.0


def test_pseudo_only_falls_back_to_root(monkeypatch):
    parts = [_part("none", "/snap/core/1", "squashfs")]
    usage = {"/": SimpleNamespace(total=200 * 1024**3, used=100 * 1024**3, percent=50.0)}
    info = _collect_with(monkeypatch, _FakePsutil(parts, usage))
    assert info.disk_total_gb == 200.0
