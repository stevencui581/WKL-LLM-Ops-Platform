"""数据模型（方案 6.3.2）。

所有对外 JSON 都由此定义，前端与后端共用同一份字段语义。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SlotState = Literal["generating", "cached", "idle", "unknown"]
AlertLevel = Literal["critical", "warning", "info"]


class ModelInfo(BaseModel):
    name: str = ""
    ftype: str = ""
    n_params: int = 0
    n_ctx: int = 0
    n_ctx_train: int = 0
    n_vocab: int = 0
    size_bytes: int = 0


class GpuProcess(BaseModel):
    pid: int
    name: str
    mem_mib: int | None = None
    sm_pct: float | None = None


class GpuInfo(BaseModel):
    index: int
    name: str = ""
    uuid: str = ""
    pci: str = ""
    temp_c: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    mem_used_mib: int | None = None
    mem_total_mib: int | None = None
    util_gpu_pct: float | None = None
    util_mem_pct: float | None = None
    clk_sm_mhz: int | None = None
    clk_mem_mhz: int | None = None
    pcie_gen: int | None = None
    pcie_width: int | None = None
    #: 风扇转速；无风扇卡（SXM2 等）为 None → 界面显示「—」（v0.4 F3）
    fan_pct: int | None = None
    #: 近似带宽；型号未收录时为 None（v0.4 F2，绝不套用别的卡）
    bandwidth_gbps: float | None = None
    mem_type: str = ""
    vendor: str = ""
    processes: list[GpuProcess] = Field(default_factory=list)


class SlotInfo(BaseModel):
    id: int
    n_ctx: int = 0
    is_processing: bool = False
    id_task: int = -1
    n_prompt_tokens: int = 0
    n_prompt_tokens_cache: int = 0
    n_prompt_tokens_processed: int = 0
    n_decoded: int = 0
    speculative_types: str = ""
    max_tokens: int | None = None
    state: SlotState = "unknown"
    source: str | None = None  # /slots 不提供；取不到时为 None，前端显示「未知」


class KvBlock(BaseModel):
    used_tokens: int = 0
    total_tokens: int = 0
    pct: float | None = None
    remaining_tokens: int = 0
    slots: list[SlotInfo] = Field(default_factory=list)
    #: v0.4 §5.3：unified（-kvu 统一池）/ per_slot（每槽独立）/ unknown
    capacity_mode: Literal["unified", "per_slot", "unknown"] = "unknown"
    #: 判定依据：unit_kv_flag / unit_ctx_math / journal / props / override / none
    capacity_source: str = "none"
    #: 由后端生成的说明文案，前端直接显示（消除前端硬编码）
    label: str = ""
    #: v0.4 §5.4：KV 量化类型与来源（unit / default / unknown）
    kv_quant: str = ""
    kv_quant_source: str = "unknown"


class RecentRequest(BaseModel):
    """最近一次请求的性能快照（方案 6.2.1「最近请求明细」）。"""

    prefill_tps: float | None = None
    prefill_tokens: int | None = None
    decode_tps: float | None = None
    decode_tokens: int | None = None
    total_tokens: int | None = None
    mtp_accept: float | None = None
    draft_mean_len: float | None = None
    slot_id: int | None = None
    task_id: int | None = None
    ts: float | None = None


class KpiBlock(BaseModel):
    decode_tps: float | None = None
    decode_tps_source: str = "none"  # tg_3s / tg / slots_delta / none
    prefill_tps: float | None = None
    mtp_accept: float | None = None
    draft_mean_len: float | None = None
    processing: int = 0
    slots_total: int = 0
    deferred: int | None = None
    vram_used_mib: int | None = None
    vram_total_mib: int | None = None
    generated_total: int | None = None
    generated_total_exact: bool = False
    recent: RecentRequest | None = None


class SystemInfo(BaseModel):
    cpu_pct: float | None = None
    cpu_per_core: list[float] = Field(default_factory=list)
    load1: float | None = None
    load5: float | None = None
    load15: float | None = None
    mem_total_mb: int | None = None
    mem_used_mb: int | None = None
    mem_pct: float | None = None
    swap_total_mb: int | None = None
    swap_used_mb: int | None = None
    disk_total_gb: float | None = None
    disk_used_gb: float | None = None
    disk_pct: float | None = None
    net_rx_kbps: float | None = None
    net_tx_kbps: float | None = None


class SelfInfo(BaseModel):
    """控制台自身开销（TASK-21）。"""

    cpu_pct: float | None = None
    rss_mb: float | None = None
    threads: int | None = None
    ws_clients: int = 0
    uptime_s: float | None = None


class Alert(BaseModel):
    code: str
    level: AlertLevel
    message: str
    since: float
    value: float | None = None
    detail: str = ""


class RuntimeConfig(BaseModel):
    """运行时配置徽标（方案 6.4.4；v0.4 增加来源标记）。"""

    product_name: str = ""
    product_version: str = ""
    model_name: str = ""
    model_ftype: str = ""
    n_ctx: int = 0
    n_ctx_train: int = 0
    total_slots: int = 0
    kv_quant: str = ""
    kv_quant_source: str = "unknown"  # unit / default / unknown
    spec_types: str = ""
    draft_n_max: int = 0
    flash_attn: bool = True
    tensor_split: str = ""
    split_mode: str = ""
    tensor_parallel: bool = False
    gpu_count: int = 0
    gpu_bandwidth_label: str = ""
    metrics_enabled: bool = False
    slots_enabled: bool = True
    ui_enabled: bool = True
    platform: str = ""
    badges: list[str] = Field(default_factory=list)
    #: v0.4.3 §6.4：结构化徽标 —— 后端给 key/value，前端按当前语言渲染。
    #: 旧的 ``badges``（中文串）保留，供 curl / 非 JS 消费者使用。
    badge_items: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# v0.4 硬件 / 软件栈识别（全部运行时探测，见升级方案 §5）
# ---------------------------------------------------------------------------
AccelStatus = Literal["installed", "missing", "unknown"]


class DmiInfo(BaseModel):
    """整机 / 主板 / BIOS。免 root 可读；字段可能缺失 → 空串表示「未知」。"""

    sys_vendor: str = ""
    product_name: str = ""
    product_version: str = ""
    board_vendor: str = ""
    board_name: str = ""
    bios_vendor: str = ""
    bios_version: str = ""
    bios_date: str = ""


class CpuInfo(BaseModel):
    model: str = ""
    vendor: str = ""
    sockets: int = 0
    cores_per_socket: int = 0
    threads_per_core: int = 0
    logical: int = 0
    l3_cache: str = ""
    numa_nodes: int = 0
    arch: str = ""


class MemoryInfo(BaseModel):
    total_gib: float = 0.0
    available_gib: float = 0.0
    swap_gib: float = 0.0


class DiskPartition(BaseModel):
    name: str = ""
    mountpoint: str = ""
    fstype: str = ""
    size_gib: float = 0.0
    used_gib: float = 0.0
    used_pct: float | None = None


class DiskDevice(BaseModel):
    name: str = ""
    size_gib: float = 0.0
    model: str = ""
    rota: bool | None = None
    partitions: list[DiskPartition] = Field(default_factory=list)


class AccelComponent(BaseModel):
    """依赖组件（CUDA Toolkit / cuDNN / NCCL / Container Toolkit / ROCm ...）。"""

    name: str = ""
    version: str | None = None
    status: AccelStatus = "unknown"
    detail: str = ""


class AccelVendor(BaseModel):
    """某一厂家的算力卡集合（NVIDIA 或 AMD）。``present=False`` 时前端整段不渲染。"""

    present: bool = False
    vendor: str = ""
    count: int = 0
    models: list[str] = Field(default_factory=list)
    model: str = ""
    architecture: str = ""
    compute_cap: str = ""
    memory_gib_each: float | None = None
    pci_ids: list[str] = Field(default_factory=list)
    pci_addresses: list[str] = Field(default_factory=list)
    vbios: list[str] = Field(default_factory=list)
    topology: str = ""
    nvlink: bool | None = None
    fan_present: bool | None = None
    bandwidth_gbps: float | None = None
    mem_type: str = ""
    #: v0.4.3 §6.4：型号是否在规格表中（false → 前端提示"未收录"，语言无关）
    bandwidth_known: bool | None = None
    driver_name: str = ""
    driver_version: str = ""
    cuda_driver_version: str = ""
    rocm_version: str = ""
    components: list[AccelComponent] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TorchInfo(BaseModel):
    installed: bool = False
    version: str | None = None
    backend: str | None = None  # "CUDA 12.8" / "ROCm 6.1" / None
    interpreter: str = ""
    probed_paths: list[str] = Field(default_factory=list)


class PythonInfo(BaseModel):
    version: str = ""
    executable: str = ""
    conda: bool = False
    torch: TorchInfo = Field(default_factory=TorchInfo)


class HardwareInfo(BaseModel):
    """硬件与运行环境全量识别结果（v0.4 §8.1 的 /api/hardware）。"""

    collected_ts: float = 0.0
    age_s: float = 0.0
    stale: bool = False
    vendors: list[str] = Field(default_factory=list)
    dmi: DmiInfo = Field(default_factory=DmiInfo)
    cpu: CpuInfo = Field(default_factory=CpuInfo)
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    disks: list[DiskDevice] = Field(default_factory=list)
    accelerators_summary: dict = Field(default_factory=dict)
    accelerators: dict[str, AccelVendor] = Field(default_factory=dict)
    python: PythonInfo = Field(default_factory=PythonInfo)
    unknown_fields: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class AccelBadge(BaseModel):
    """顶栏标识1 用（v0.4 R1）。"""

    vendor: str = ""
    model: str = ""
    count: int = 0
    tensor_parallel: bool = False
    text: str = ""
    present: bool = False


class BaselineMetric(BaseModel):
    """单项基线状态（v0.4 §7）。"""

    state: Literal["learning", "ready", "disabled"] = "learning"
    samples: int = 0
    required: int = 0
    value: float | None = None
    source: Literal["learned", "manual", "none"] = "none"


class BaselineState(BaseModel):
    mtp: BaselineMetric = Field(default_factory=BaselineMetric)
    decode: BaselineMetric = Field(default_factory=BaselineMetric)


class MetricSnapshot(BaseModel):
    seq: int = 0
    ts: float = 0.0
    stale: dict[str, bool] = Field(default_factory=dict)
    model: ModelInfo = Field(default_factory=ModelInfo)
    kpi: KpiBlock = Field(default_factory=KpiBlock)
    kv: KvBlock = Field(default_factory=KvBlock)
    gpus: list[GpuInfo] = Field(default_factory=list)
    system: SystemInfo = Field(default_factory=SystemInfo)
    self_info: SelfInfo = Field(default_factory=SelfInfo)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    alerts: list[Alert] = Field(default_factory=list)
    #: v0.4：告警阈值随快照下发，前端不再硬编码（F5）
    #: v0.6.1：由 ``app/payload.py::thresholds_of()`` 填充 —— 原先这个字段
    #: **从未被赋值**，形状对但内容是空字典，前端因此退回硬编码值。
    thresholds: dict = Field(default_factory=dict)
    #: v0.4：自动基线状态（§7）
    baseline: BaselineState = Field(default_factory=BaselineState)
    #: v0.4：顶栏算力卡摘要（R1）
    accelerator_badge: AccelBadge = Field(default_factory=AccelBadge)
    #: v0.4：llama-server 运行时长（顶栏「服务运行」，决策 B1）
    llama_uptime_s: float | None = None
    #: v0.4：硬件清点时间戳。前端据此判断是否需要重新拉 /api/hardware
    #: （只在变化时拉取，避免每 2 秒推送 1.5KB 的硬件块）
    hardware_ts: float = 0.0
    #: v0.5：推理框架识别结果。
    #:
    #: **必须在快照里**，不能只挂在 REST 路由上 —— 页面每 2 秒被 WebSocket
    #: 推送覆盖一次，若快照不含此字段，顶栏「框架」徽标会先正确显示一瞬、
    #: 随后退回「识别中…」并永久停在那里（实测踩过的坑）。
    framework: dict = Field(default_factory=dict)
    #: v0.6.1：品牌信息。
    #:
    #: 原先只在 ``/api/overview`` 里手工拼，因此**页面每 2 秒被 WS 覆盖后
    #: 版号/产品名会退回静态兜底值**。前端 ``renderOverview()`` 会读
    #: ``o.branding``，所以它必须在快照里（见 ``app/payload.py`` 的文件头）。
    branding: dict = Field(default_factory=dict)
    #: v0.6.1：就绪状态与降级原因。
    #:
    #: ``ready``/``reasons``/``reason_codes`` 必须随快照下发 —— 前端用它决定
    #: 是否显示降级横幅；缺失时横幅永不出现、总状态永远显示 ok。
    health: dict = Field(default_factory=dict)


class LogLine(BaseModel):
    ts: str = ""
    epoch: float = 0.0
    level: str = "I"
    slot: int | None = None
    task: int | None = None
    text: str = ""
    highlight: str | None = None
    #: 行类型（v0.6）。
    #:
    #: ``journalctl`` 在查询范围**跨重启**时会插入没有时间戳的分隔行，例如::
    #:
    #:     -- Boot c62e718a0de6467e9ab147ad01b90086 --
    #:
    #: 这类行 ``ts``/``epoch`` 为空。早期版本把它当普通日志行返回，
    #: 前端显示成一行空白时间戳，守卫也误判为"时间格式错误"。
    #: 现在显式标注，前端据此渲染为分隔条。
    kind: str = "log"  # log | separator


class ServiceStatus(BaseModel):
    unit: str = ""
    active: str = "unknown"
    sub: str = "unknown"
    since: str = ""
    n_restarts: int = 0
    elapsed_s: float | None = None
    progress: str = ""
    #: v0.4.3 §6.4：语言无关的进度枚举（starting / model_loading / waiting_ready /
    #: running / failed），前端按当前语言渲染；``progress`` 为中文兼容串。
    progress_code: str = ""
    eta_s: int = 0
    busy: bool = False
    authorized: bool = True
    #: v0.4 决策 B1：被监控服务已运行秒数（来自 systemd 单调时间戳）
    uptime_s: float | None = None
