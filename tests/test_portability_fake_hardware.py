"""可移植性测试：用**伪造的硬件**验证换机器也能正确工作（v0.4 §9.1）。

覆盖 4 种部署形态：
  ① NVIDIA A100 单卡
  ② AMD MI210（无 nvidia-smi）
  ③ 无算力卡
  ④ NVIDIA 4 卡

断言重点：
  * 卡数完全跟随输入，不固定 2 张；
  * AMD 机器上不出现 NVIDIA 段落，反之亦然（R4）；
  * 未收录型号的带宽为 None（不套用别的卡的值）；
  * 虚拟显卡（QEMU 1234:1111）不被计入算力卡。
"""

from __future__ import annotations

import asyncio

from app.collectors.hardware import (
    HardwareCollector,
    parse_lsblk_json,
    parse_lscpu,
    parse_nvidia_smi_topo,
)
from app.config import Settings
from app.services import accel, gpu_spec

# ===========================================================================
# 厂家探测（R4 条件渲染的唯一依据）
# ===========================================================================
LSPCI_NVIDIA_2 = """\
00:01.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
01:00.0 3D controller [0302]: NVIDIA Corporation GV100GL [Tesla V100 SXM2 16GB] [10de:1db1] (rev a1)
02:00.0 3D controller [0302]: NVIDIA Corporation GV100GL [Tesla V100 SXM2 16GB] [10de:1db1] (rev a1)
"""

LSPCI_AMD_1 = """\
00:01.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
03:00.0 Display controller [0380]: Advanced Micro Devices, Inc. [AMD/ATI] Aldebaran [Instinct MI210] [1002:740f]
"""

LSPCI_NVIDIA_4 = """\
01:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)
02:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)
03:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)
04:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)
"""

LSPCI_NONE = """\
00:01.0 VGA compatible controller [0300]: Device [1234:1111] (rev 02)
00:1f.0 ISA bridge [0601]: Intel Corporation Device [8086:a30e]
"""


def test_scenario_nvidia_two_cards():
    scan = accel.parse_lspci(LSPCI_NVIDIA_2)
    assert scan.vendors == ["nvidia"]
    assert scan.count_of("nvidia") == 2
    assert accel.has_vendor(scan, "amd") is False
    # 虚拟显卡被排除，不计入卡数
    assert any("1234:1111" in e for e in scan.excluded)


def test_scenario_amd_only():
    scan = accel.parse_lspci(LSPCI_AMD_1)
    assert scan.vendors == ["amd"]
    assert scan.count_of("amd") == 1
    assert accel.has_vendor(scan, "nvidia") is False


def test_scenario_four_cards():
    scan = accel.parse_lspci(LSPCI_NVIDIA_4)
    assert scan.count_of("nvidia") == 4


def test_scenario_no_accelerator():
    scan = accel.parse_lspci(LSPCI_NONE)
    assert scan.vendors == []
    assert scan.devices == []


def test_virtual_gpu_never_counted():
    """QEMU 虚拟显卡（1234:1111）必须被排除 —— 实测踩过的坑。"""
    scan = accel.parse_lspci(LSPCI_NVIDIA_2)
    assert all(d.pci_id != "1234:1111" for d in scan.devices)
    assert scan.count_of("nvidia") == 2  # 不是 3


def test_badge_text_variants():
    assert "未检测到算力卡" in accel.badge_text("nvidia", "X", 0)
    assert "×2" in accel.badge_text("nvidia", "Tesla V100-SXM2-16GB", 2)
    assert "AMD" in accel.badge_text("amd", "MI210", 1)
    assert accel.tensor_parallel_text(True) == "张量并行 开"
    assert accel.tensor_parallel_text(False) == "张量并行 关"


# ===========================================================================
# 解析器：换机器时的输入差异
# ===========================================================================
def test_topology_phb_has_no_nvlink():
    """回归：Legend 里的 'NV#' 说明曾被误判成有 NVLink。"""
    text = (
        "GPU0\tGPU1\tCPU Affinity\tNUMA Affinity\tGPU NUMA ID\n"
        "GPU0\t X \tPHB\t0-31\t0-1\t\tN/A\n"
        "GPU1\tPHB\t X \t0-31\t0-1\t\tN/A\n"
        "\n"
        "Legend:\n"
        "\n"
        "  X    = Self\n"
        "  SYS  = Connection traversing PCIe as well as the SMP interconnect\n"
        "  PHB  = Connection traversing PCIe as well as a PCIe Host Bridge\n"
        "  NV#  = Connection traversing a bonded set of # NVLinks\n"
    )
    summary, nvlink = parse_nvidia_smi_topo(text)
    assert nvlink is False, "PHB 拓扑不得被判成有 NVLink"
    assert summary == "PHB"


def test_topology_with_ansi_colors():
    text = "\x1b[4mGPU0\tGPU1\tCPU Affinity\x1b[0m\nGPU0\t X \tSYS\t0-31\nGPU1\tSYS\t X \t0-31\n"
    summary, nvlink = parse_nvidia_smi_topo(text)
    assert summary == "SYS"
    assert nvlink is False


def test_topology_real_nvlink():
    text = "GPU0\tGPU1\tCPU Affinity\nGPU0\t X \tNV2\t0-31\nGPU1\tNV2\t X \t0-31\n"
    summary, nvlink = parse_nvidia_smi_topo(text)
    assert nvlink is True
    assert summary == "NVLink"


def test_lscpu_different_machines():
    intel = "Model name:          Intel(R) Xeon(R) Gold 6338\nSocket(s):           2\nCore(s) per socket:  32\nThread(s) per core:  2\nCPU(s):              128\nNUMA node(s):        2\nL3 cache:            48 MiB\n"
    cpu = parse_lscpu(intel)
    assert cpu.sockets == 2 and cpu.cores_per_socket == 32 and cpu.logical == 128
    assert cpu.threads_per_core == 2
    amd = "Model name:          AMD EPYC 9654 96-Core Processor\nSocket(s):           2\nCore(s) per socket:  96\nCPU(s):              192\n"
    cpu2 = parse_lscpu(amd)
    assert "EPYC" in cpu2.model and cpu2.logical == 192


def test_lsblk_filters_dvd_and_loop():
    """回归：sr0（DVD-ROM）与 loop 设备不得混进磁盘列表。"""
    payload = """{"blockdevices":[
      {"name":"sda","size":322122547200,"type":"disk","model":"QEMU HARDDISK","rota":false,
       "children":[{"name":"sda1","size":1048576,"type":"part","mountpoint":null},
                   {"name":"sda4","size":304402661376,"type":"part","mountpoint":"/"}]},
      {"name":"sr0","size":1073741312,"type":"rom","model":"QEMU DVD-ROM"},
      {"name":"loop0","size":12345,"type":"loop"},
      {"name":"nvme0n1","size":1000204886016,"type":"disk","model":"Samsung SSD 990 PRO","rota":false,
       "children":[{"name":"nvme0n1p1","size":1000204886016,"type":"part","mountpoint":"/"}]}
    ]}"""
    disks = parse_lsblk_json(payload)
    names = [d.name for d in disks]
    assert "sr0" not in names
    assert "loop0" not in names
    assert names == ["sda", "nvme0n1"]
    assert disks[0].partitions[1].mountpoint == "/"


def test_lsblk_garbage_never_raises():
    for text in ("", "not json", "{}", '{"blockdevices": null}'):
        assert parse_lsblk_json(text) == []


# ===========================================================================
# 端到端：伪造 runner 跑完整清点
# ===========================================================================
class FakeRunner:
    """按 label 返回伪造输出，模拟不同机器。"""

    def __init__(self, table: dict[str, str]):
        self.table = table

    async def run(self, argv, timeout_s=None, label=None, optional=False):
        from app.adapters.exec import CommandResult

        key = FakeRunner._key(argv, label)
        out = self.table.get(key)
        if out is None:
            # optional=True 时"命令不存在"属正常结果，不计错误（与真实 Runner 一致）
            return CommandResult(
                argv=argv, returncode=1, stdout="", stderr="", duration_ms=1.0, error="not found"
            )
        return CommandResult(argv=argv, returncode=0, stdout=out, stderr="", duration_ms=1.0)

    @staticmethod
    def _key(argv, label):
        # 采集器已显式传标签（同一可执行文件会以不同参数多次出现）
        return label or argv[0]


def _settings(tmp_path) -> Settings:
    return Settings(state_dir=str(tmp_path / "state"), hw_cache_path=str(tmp_path / "hw.json"))


def _run_hw(settings, table) -> object:
    hw = HardwareCollector(settings, FakeRunner(table))
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(hw.collect(force=True))


def test_fake_a100_single_card(tmp_path):
    table = {
        "lspci": LSPCI_NVIDIA_4.replace(
            "01:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)\n"
            "02:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)\n"
            "03:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)\n"
            "04:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)\n",
            "01:00.0 3D controller [0302]: NVIDIA Corporation GA100 [A100 SXM4 80GB] [10de:20b2] (rev a1)\n",
        ),
        "query": "0, NVIDIA A100-SXM4-80GB, 550.54.14, 81920, 8.0, 92.00.44.00.01, [N/A]\n",
        "nvidia-smi": "Driver Version: 550.54.14    CUDA Version: 12.4\n",
        "topo": "GPU0\tCPU Affinity\nGPU0\t X \t0-63\nLegend:\n  NV#  = NVLinks\n",
        "lscpu": "Model name: AMD EPYC 9654 96-Core Processor\nSocket(s): 1\nCore(s) per socket: 96\nCPU(s): 192\n",
        "lsblk": '{"blockdevices":[{"name":"nvme0n1","size":1000204886016,"type":"disk","model":"Samsung","rota":false,"children":[]}]}',
        "dpkg": "ii  cuda-toolkit-12-4  12.4.0-1\n",
        "rocm": "",
        "ctk": "",
    }
    info = _run_hw(_settings(tmp_path), table)
    assert info.vendors == ["nvidia"]
    nb = info.accelerators["nvidia"]
    assert nb.present and nb.count == 1, "单卡机器必须只显示 1 张卡"
    assert nb.model == "NVIDIA A100-SXM4-80GB"
    assert nb.bandwidth_gbps == 1555.0, "A100 应查表得到 1555，而不是 900"
    assert nb.fan_present is False, "[N/A] 风扇应为 False"
    # AMD 段必须不存在
    assert info.accelerators["amd"].present is False


def test_fake_amd_machine(tmp_path):
    table = {
        "lspci": LSPCI_AMD_1,
        "query": "",  # 无 nvidia-smi 输出
        "nvidia-smi": "",
        "topo": "",
        "rocm": "Card series:     Instinct MI210\n",
        "lscpu": "Model name: AMD EPYC 7742 64-Core Processor\nSocket(s): 2\nCPU(s): 128\n",
        "lsblk": "{}",
        "dpkg": "ii  rocm-core  6.1.0-1\nii  rocblas  4.1.0-1\n",
        "ctk": "",
    }
    info = _run_hw(_settings(tmp_path), table)
    assert info.vendors == ["amd"]
    assert info.accelerators["nvidia"].present is False, "AMD 机器不得出现 NVIDIA 段"
    ab = info.accelerators["amd"]
    assert ab.present and ab.count >= 1
    assert ab.rocm_version == "6.1.0"
    assert ab.bandwidth_gbps == 1638.0, "MI210 应查表得到 1638"
    comp_names = [c.name for c in ab.components]
    assert any("ROCm" in n for n in comp_names)
    assert not any("CUDA" in n for n in comp_names), "AMD 机器不得出现 CUDA 组件"


def test_fake_no_accelerator(tmp_path):
    table = {
        "lspci": LSPCI_NONE,
        "query": "",
        "nvidia-smi": "",
        "topo": "",
        "rocm": "",
        "lscpu": "Model name: Test CPU\nCPU(s): 4\n",
        "lsblk": "{}",
        "dpkg": "",
        "ctk": "",
    }
    info = _run_hw(_settings(tmp_path), table)
    assert info.vendors == []
    assert info.accelerators["nvidia"].present is False
    assert info.accelerators["amd"].present is False
    assert "accelerators" in info.unknown_fields


def test_fake_unknown_gpu_model_has_no_bandwidth(tmp_path):
    """未收录型号：带宽必须是 None，界面显示「—」，绝不套用别的卡（F2）。"""
    table = {
        "lspci": ("01:00.0 3D controller [0302]: FutureCorp HyperChip 9000 [abcd:1234] (rev a1)\n"),
        "query": "0, FutureCorp HyperChip 9000, 1.0, 24576, 9.0, vbios, [N/A]\n",
        "nvidia-smi": "Driver Version: 1.0    CUDA Version: 99.0\n",
        "topo": "",
        "rocm": "",
        "lscpu": "Model name: X\n",
        "lsblk": "{}",
        "dpkg": "",
        "ctk": "",
    }
    settings = _settings(tmp_path)
    settings.accel_vendor_allowlist = ("10de", "1002", "abcd")  # 允许这家厂商
    info = HardwareCollector(settings, FakeRunner(table))
    info = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(info.collect(force=True))
    nb = info.accelerators.get("nvidia")
    if nb and nb.present:
        assert nb.bandwidth_gbps is None
        assert any("未收录" in n for n in nb.notes)
    # 无论是否被厂商白名单接受，都不得凭空给出带宽
    assert gpu_spec.bandwidth_of("FutureCorp HyperChip 9000") is None
