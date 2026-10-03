#!/usr/bin/env python
"""硬件清点采集器实机验证（v0.4 TASK-34~37）。

cd /home/llmops/llm-console && ./venv/bin/python probes/verify_hardware.py
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, "/home/llmops/llm-console")

from app.adapters.exec import CommandRunner  # noqa: E402
from app.collectors.hardware import HardwareCollector  # noqa: E402
from app.config import Settings  # noqa: E402


def main() -> int:
    s = Settings()
    # 用临时缓存路径，避免污染生产 state
    s.hw_cache_path = "/tmp/hw_probe.json"
    runner = CommandRunner(s)
    hw = HardwareCollector(s, runner)

    t0 = time.monotonic()
    info = asyncio.run(hw.collect(force=True))
    ms = (time.monotonic() - t0) * 1000

    print(f"=== 清点耗时 {ms:.0f} ms（预算 200ms）===")
    print(f"    超预算: {'是 ✗' if ms > 200 else '否 ✓'}")
    print()

    print("=== ① 服务器硬件 ===")
    print(f"  整机厂商/型号 : {info.dmi.sys_vendor or '未知'} / {info.dmi.product_name or '未知'}")
    print(
        f"  BIOS          : {info.dmi.bios_vendor or '未知'} {info.dmi.bios_version or ''} {info.dmi.bios_date or ''}"
    )
    c = info.cpu
    print(f"  CPU           : {c.model or '未知'}")
    print(
        f"                  {c.sockets} 路 × {c.cores_per_socket} 核 = {c.logical} 逻辑核, "
        f"threads/core={c.threads_per_core}, L3={c.l3_cache}, NUMA={c.numa_nodes}"
    )
    m = info.memory
    print(f"  内存          : {m.total_gib} GiB（可用 {m.available_gib}）Swap {m.swap_gib} GiB")
    for d in info.disks:
        print(f"  磁盘          : {d.name} {d.size_gib} GiB model={d.model or '—'} rota={d.rota}")
        for p in d.partitions:
            print(
                f"                  └ {p.name} {p.mountpoint or '—'} {p.fstype} "
                f"{p.size_gib}G 已用 {p.used_gib}G ({p.used_pct}%)"
            )

    print()
    print("=== ② 算力卡与依赖环境 ===")
    print(f"  探测到的厂家  : {info.vendors or '无'}")
    for vendor, b in info.accelerators.items():
        if not b.present:
            print(f"  [{vendor}] present=False（前端整段不渲染）")
            continue
        print(f"  [{vendor}] count={b.count} model={b.model}")
        print(f"            显存/卡={b.memory_gib_each} GiB  compute_cap={b.compute_cap}")
        print(f"            PCI={b.pci_ids} 地址={b.pci_addresses}")
        print(f"            拓扑={b.topology or '—'} NVLink={b.nvlink}")
        print(f"            风扇存在={b.fan_present}")
        print(f"            带宽={b.bandwidth_gbps} GB/s [{b.mem_type}]")
        print(f"            驱动={b.driver_name} {b.driver_version}  驱动支持CUDA={b.cuda_driver_version}")
        if b.rocm_version:
            print(f"            ROCm={b.rocm_version}")
        for comp in b.components:
            print(f"            · {comp.name}: {comp.version or '未安装'} [{comp.status}] {comp.detail}")
        for note in b.notes:
            print(f"            ! {note}")

    print()
    print("=== ③ Python 与框架 ===")
    p = info.python
    print(f"  Python   : {p.version}  ({p.executable})  conda={p.conda}")
    t = p.torch
    if t.installed:
        print(f"  PyTorch  : {t.version}  backend={t.backend}")
    else:
        print("  PyTorch  : 未安装（如实显示，不猜测）")

    print()
    print("=== 未知字段与错误 ===")
    print(f"  unknown_fields: {info.unknown_fields}")
    print(f"  errors        : {info.errors}")

    print()
    print("=== 关键断言 ===")
    fails = []
    if info.accelerators.get("amd", None) and info.accelerators["amd"].present:
        fails.append("本机无 AMD 卡，amd.present 不应为 True")
    if info.vendors and "nvidia" in info.vendors:
        nb = info.accelerators["nvidia"]
        if nb.count < 1:
            fails.append("NVIDIA 卡数应为正")
        if nb.bandwidth_gbps is None:
            fails.append("V100 应在规格表命中，带宽不应为 None")
    if not info.cpu.model:
        fails.append("CPU 型号不应为空")
    if info.memory.total_gib <= 0:
        fails.append("内存总量应大于 0")
    if info.python.torch.installed:
        fails.append("本机未装 PyTorch，installed 不应为 True")
    for f in fails:
        print(f"  [FAIL] {f}")
    if not fails:
        print("  [ OK ] 全部关键断言通过")

    print()
    print("HW_PROBE_OK" if not fails else "HW_PROBE_FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
