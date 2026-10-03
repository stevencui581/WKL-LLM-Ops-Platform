"""硬件/软件栈解析测试（v0.4 TASK-34~37）。

夹具来源：目标服务器实测输出（**仅用于测试**，不得进入生产逻辑）。
"""

from __future__ import annotations

import json

import pytest

from app.collectors.hardware import (
    collect_python,
    parse_cuda_version_file,
    parse_cudnn_header,
    parse_dpkg_packages,
    parse_lsblk_json,
    parse_lscpu,
    parse_meminfo,
    parse_nccl_header,
    parse_nvcc_version,
    parse_nvidia_smi_header,
    parse_rocm_smi,
    read_dmi,
)
from app.config import Settings

# ---------------------------------------------------------------- 夹具（253 实测）
LSCPU_SAMPLE = """\
Architecture:                            x86_64
CPU(s):                                  32
Vendor ID:                               GenuineIntel
Model name:                              Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz
Socket(s):                               2
Core(s) per socket:                      16
Thread(s) per core:                      1
NUMA node(s):                            2
L3 cache:                                32 MiB (2 instances)
"""

MEMINFO_SAMPLE = """\
MemTotal:       57679204 kB
MemAvailable:   55116200 kB
SwapTotal:      16777212 kB
"""

LSBLK_SAMPLE = json.dumps(
    {
        "blockdevices": [
            {
                "name": "sda",
                "size": 322122547200,
                "type": "disk",
                "model": "QEMU HARDDISK",
                "rota": False,
                "children": [
                    {"name": "sda1", "size": 1048576, "type": "part", "mountpoint": None},
                    {"name": "sda2", "size": 536870912, "type": "part", "mountpoint": "/boot"},
                    {"name": "sda3", "size": 17179869184, "type": "part", "mountpoint": "[SWAP]"},
                    {"name": "sda4", "size": 304402661376, "type": "part", "mountpoint": "/"},
                ],
            },
            {"name": "sr0", "size": 1073741312, "type": "rom", "model": "QEMU DVD-ROM"},
        ]
    }
)

NVIDIA_SMI_SAMPLE = """\
Fri Oct  2 00:00:00 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.173.02             Driver Version: 580.173.02     CUDA Version: 13.0     |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
|=========================================+========================+======================|
|   0  Tesla V100-SXM2-16GB           Off | 00000000:01:00.0 Off |                    0 |
+-----------------------------------------+------------------------+----------------------+
"""

CUDA_VERSION_JSON_SAMPLE = json.dumps(
    {
        "cuda": {"name": "CUDA SDK", "version": "12.8.2"},
        "cuda_cccl": {"name": "CUDA C++ Core Compute Libraries", "version": "12.8.90"},
    }
)

CUDNN_HEADER_SAMPLE = """\
#define CUDNN_MAJOR 9
#define CUDNN_MINOR 22
#define CUDNN_PATCHLEVEL 0
#define CUDNN_VERSION (CUDNN_MAJOR * 10000 + CUDNN_MINOR * 100 + CUDNN_PATCHLEVEL)
"""

DPKG_SAMPLE = """\
Desired=Unknown/Install/Remove/Purge/Hold
||/ Name                          Version            Architecture Description
+++-=============================-==================-============-=================================
ii  cuda-cudart-12-8              12.8.90-1          amd64        CUDA Runtime
ii  cudnn9-cuda-12                9.22.0.52-1        amd64        cuDNN
ii  cuda-command-line-tools-12-8  12.8.2-1           amd64        CUDA tools
"""


# ---------------------------------------------------------------- 解析
def test_parse_lscpu_real():
    cpu = parse_lscpu(LSCPU_SAMPLE)
    assert cpu.model == "Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz"
    assert cpu.sockets == 2
    assert cpu.cores_per_socket == 16
    assert cpu.threads_per_core == 1
    assert cpu.logical == 32
    assert cpu.numa_nodes == 2
    assert "32 MiB" in cpu.l3_cache
    assert cpu.vendor == "GenuineIntel"


def test_parse_lscpu_empty():
    cpu = parse_lscpu("")
    assert cpu.model == "" and cpu.logical == 0


def test_parse_meminfo_real():
    m = parse_meminfo(MEMINFO_SAMPLE)
    assert m.total_gib == pytest.approx(55.01, abs=0.05)
    assert m.available_gib == pytest.approx(52.56, abs=0.1)
    assert m.swap_gib == pytest.approx(16.0, abs=0.01)


def test_parse_lsblk_real():
    disks = parse_lsblk_json(LSBLK_SAMPLE)
    assert len(disks) == 1
    assert disks[0].name == "sda"
    assert disks[0].size_gib == pytest.approx(300.0, abs=0.1)
    assert disks[0].rota is False
    mounts = {p.name: p.mountpoint for p in disks[0].partitions}
    assert mounts["sda4"] == "/"
    assert mounts["sda2"] == "/boot"


def test_parse_nvidia_header():
    drv, cuda = parse_nvidia_smi_header(NVIDIA_SMI_SAMPLE)
    assert drv == "580.173.02"
    assert cuda == "13.0"


def test_parse_nvidia_header_missing():
    assert parse_nvidia_smi_header("") == ("", "")


def test_parse_cuda_version_json():
    assert parse_cuda_version_file(CUDA_VERSION_JSON_SAMPLE) == "12.8.2"


def test_parse_cuda_version_txt_fallback():
    assert parse_cuda_version_file("CUDA Version 12.4.1\n") == "12.4.1"


def test_parse_cuda_version_garbage():
    assert parse_cuda_version_file("") == ""
    assert parse_cuda_version_file("nothing") == ""


def test_parse_nvcc_version():
    assert (
        parse_nvcc_version(
            "nvcc: NVIDIA (R) Cuda compiler driver\nCuda compilation tools, release 12.8, V12.8.93"
        )
        == "12.8"
    )


def test_parse_cudnn_header():
    assert parse_cudnn_header(CUDNN_HEADER_SAMPLE) == "9.22.0"


def test_parse_cudnn_header_missing():
    assert parse_cudnn_header("") == ""
    assert parse_cudnn_header("#define OTHER 1") == ""


def test_parse_nccl_header():
    text = "#define NCCL_MAJOR 2\n#define NCCL_MINOR 21\n#define NCCL_PATCH 5\n"
    assert parse_nccl_header(text) == "2.21.5"
    assert parse_nccl_header("") == ""


def test_parse_dpkg_packages():
    pkgs = parse_dpkg_packages(DPKG_SAMPLE)
    assert pkgs.get("cudnn9-cuda-12") == "9.22.0.52-1"
    assert pkgs.get("cuda-cudart-12-8") == "12.8.90-1"


def test_parse_dpkg_ignores_header():
    pkgs = parse_dpkg_packages(DPKG_SAMPLE)
    assert "Name" not in pkgs
    assert "Version" not in pkgs


def test_parse_rocm_smi():
    text = (
        "======================= ROCm System Management Interface =======================\n"
        "Card series:          Instinct MI210\n"
        "Card series:          Instinct MI210\n"
    )
    assert parse_rocm_smi(text) == ["Instinct MI210"]


# ---------------------------------------------------------------- DMI
def test_read_dmi_missing_dir(tmp_path):
    info = read_dmi(str(tmp_path / "nope"))
    assert info.sys_vendor == "" and info.bios_vendor == ""


def test_read_dmi_partial_fields(tmp_path):
    """字段缺失（board_* 在 目标 上不存在）必须容错为「未知」，不报错。"""
    (tmp_path / "sys_vendor").write_text("QEMU\n", encoding="utf-8")
    (tmp_path / "product_name").write_text("Standard PC (Q35 + ICH9, 2009)\n", encoding="utf-8")
    (tmp_path / "bios_vendor").write_text("SeaBIOS\n", encoding="utf-8")
    info = read_dmi(str(tmp_path))
    assert info.sys_vendor == "QEMU"
    assert info.product_name.startswith("Standard PC")
    assert info.board_name == "", "缺失字段应为空（未知），不得报错或编造"


# ---------------------------------------------------------------- Python
def test_collect_python_reports_real_interpreter():
    info = collect_python(Settings())
    assert info.version
    assert info.executable
    assert isinstance(info.conda, bool)


def test_collect_python_torch_missing_is_honest():
    """未安装时必须 installed=False，不得给出假版本号（原则 P3）。"""
    info = collect_python(Settings())
    if not info.torch.installed:
        assert info.torch.version is None
        assert info.torch.backend is None


def test_settings_paths_are_configurable():
    s = Settings()
    assert s.hardware_ttl_s > 0
    assert s.hw_cmd_timeout_s > 0
    assert s.baseline_min_samples > 0
    assert s.accel_vendor_allowlist
    assert s.accel_pci_denylist
    assert s.kv_quant_show_default in (True, False)
