"""WKL-LLM运维平台 v0.4 —— 唯一配置源。

设计约束（方案 6.3.1 / 12.7 第 5 条 / v0.4 P2）：
  * 所有阈值、端口、路径、频率集中在此，业务代码中不得出现魔法数字；
  * **不得出现任何特定服务器的路径/型号/数量** —— 路径由本文件位置自定位，
    硬件信息一律运行时探测（v0.4 全自动识别原则 P1/P2）；
  * 设置 ``extra="forbid"``，环境变量拼错时启动即失败，而不是静默使用默认值；
  * 配置项可用环境变量覆盖，前缀 ``LLMCONSOLE_``，嵌套字段用 ``__`` 分隔。

开发文档依据：V4.1 第 6.2 节（指标）、6.3.4（告警阈值）、12.4（运行环境）；
v0.4 升级方案 §5（识别项）、§7（自动基线）、§10（配置项）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 项目根目录 —— 由本文件位置推导，不写死部署路径（v0.4 F8 修复）
PKG_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLMCONSOLE_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="forbid",
    )

    # ------------------------------------------------------------------
    # 品牌与署名 —— 顶部标识与底部开发者信息只从这里取（方案 6.4.6/6.4.7）
    # 版本号只有这一处定义，其余位置一律引用（v0.4 R8 / test_branding.py）
    # ------------------------------------------------------------------
    product_version: str = "v0.6"
    product_name: str = "WKL-LLM运维平台v0.6"
    product_name_spaced: str = "WKL-LLM运维平台 v0.6"
    developer: str = "WKL-LLM运维平台"
    develop_date: str = "2026.10.01"

    # ------------------------------------------------------------------
    # 服务监听（方案 12.4：固定 8081，8080 被 llama-server 占用）
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = Field(default=8081, gt=0, lt=65536)

    # ------------------------------------------------------------------
    # 被监控对象（全部可覆盖，不假定具体部署）
    # ------------------------------------------------------------------
    llama_base_url: str = "http://127.0.0.1:8080"
    llama_unit: str = "llm-infer.service"
    console_unit: str = "llm-console.service"
    nvidia_smi: str = "nvidia-smi"
    rocm_smi: str = "rocm-smi"
    journalctl: str = "journalctl"
    systemctl: str = "systemctl"

    # ------------------------------------------------------------------
    # 采集频率与超时（方案 6.1.5 / 6.1 采集器表）
    # ------------------------------------------------------------------
    poll_interval_s: float = Field(default=2.0, gt=0)
    config_poll_interval_s: float = Field(default=60.0, gt=0)
    pmon_interval_s: float = Field(default=10.0, gt=0)
    http_timeout_s: float = Field(default=1.0, gt=0)
    props_timeout_s: float = Field(default=3.0, gt=0)
    cmd_timeout_s: float = Field(default=2.0, gt=0)
    cmd_kill_grace_s: float = Field(default=3.0, gt=0)

    # ------------------------------------------------------------------
    # 缓冲与背压（方案 12.7 第 8~13 条）
    # ------------------------------------------------------------------
    history_points: int = Field(default=150, gt=0)  # 150 点 = 5 分钟
    log_queue_max: int = Field(default=2000, gt=0)
    log_ring_max: int = Field(default=1000, gt=0)
    ws_queue_max: int = Field(default=100, gt=0)
    ws_send_timeout_s: float = Field(default=5.0, gt=0)
    ws_ping_interval_s: float = Field(default=30.0, gt=0)
    journal_backfill_lines: int = Field(default=40, gt=0)
    #: 首次回填的扫描窗口。放宽到 7 天，保证空闲服务器也有日志可显示。
    journal_since: str = "-7d"
    stream_reader_limit: int = Field(default=1 << 20, gt=0)

    # ------------------------------------------------------------------
    # 运行时路径 —— 自定位，默认落在项目根下（v0.4 F8 修复）
    # ------------------------------------------------------------------
    state_dir: str = str(PKG_ROOT / "state")
    static_dir: str = str(PKG_ROOT / "static")
    releases_dir: str = str(PKG_ROOT / "releases")

    # ------------------------------------------------------------------
    # 降级（方案 7.5 / TASK-13）
    # ------------------------------------------------------------------
    stale_after_misses: int = Field(default=3, gt=0)

    # ------------------------------------------------------------------
    # 告警阈值（方案 6.3.4）
    # 注意：MTP 与解码吞吐的基线**不再写死**，改由自动基线学习器产出
    # （v0.4 §7 / F4）；此处仅保留人工覆盖入口，None 表示自动学习。
    # ------------------------------------------------------------------
    gpu_temp_warn_c: float = 83.0
    gpu_temp_crit_c: float = 87.0
    gpu_temp_sustain_s: float = 120.0
    #: 告警阈值取自方案 6.3.4 告警表（>90% 警告，>95% 严重）
    vram_warn_pct: float = 90.0
    vram_crit_pct: float = 95.0
    #: 卡片配色阈值取自方案 5.3（≥85% 橙），与告警阈值分开
    vram_color_warn_pct: float = 85.0
    kv_warn_pct: float = 85.0
    kv_crit_pct: float = 95.0
    kv_sustain_s: float = 60.0
    #: 功耗告警改为**相对每张卡自己的 power_limit**（v0.4 F7 修复）
    power_warn_pct: float = 90.0
    mtp_drop_ratio: float = 0.80
    mtp_sustain_s: float = 300.0
    decode_drop_ratio: float = 0.50
    decode_sustain_s: float = 300.0
    service_down_ticks: int = 2
    deferred_sustain_s: float = 300.0
    #: 人工覆盖基线；None = 用自动学习结果（v0.4 §7 决策）
    mtp_accept_baseline: float | None = None
    decode_baseline_tps: float | None = None

    # ------------------------------------------------------------------
    # 自动基线学习器（v0.4 §7 / F4）
    # ------------------------------------------------------------------
    baseline_warmup_s: float = Field(default=600.0, ge=0)
    baseline_min_samples: int = Field(default=20, gt=0)
    baseline_quantile: float = Field(default=0.50, gt=0, lt=1)
    #: 空 = state_dir/baseline.json
    baseline_persist_path: str = ""
    baseline_relearn: bool = False

    # ------------------------------------------------------------------
    # 硬件 / 软件栈清点（v0.4 §5）
    # ------------------------------------------------------------------
    hardware_ttl_s: float = Field(default=600.0, gt=0)
    hw_cmd_timeout_s: float = Field(default=3.0, gt=0)
    #: 空 = state_dir/hardware.json
    hw_cache_path: str = ""
    hw_external_python: str = ""
    hw_enable_smartctl: bool = False
    hw_show_launch_args: bool = False
    #: 认可的算力卡 PCI 厂商 ID（NVIDIA 10de / AMD 1002）
    accel_vendor_allowlist: tuple[str, ...] = ("10de", "1002")
    #: 明确排除的虚拟显卡（QEMU 1234:1111 等）
    accel_pci_denylist: tuple[str, ...] = ("1234:1111",)

    # ------------------------------------------------------------------
    # KV 池（v0.4 §5.3 / §5.4）
    # ------------------------------------------------------------------
    #: 空 = 自动判定（unit -kvu → -c 算术关系 → journal 日志）；
    #: 可强制 "unified" / "per_slot"
    kv_mode_override: Literal["", "unified", "per_slot"] = ""
    #: 未配置 -ctk/-ctv 时是否显示「f16（默认）」；false 则显示「未知」
    kv_quant_show_default: bool = True

    # ------------------------------------------------------------------
    # 服务管理（方案 7.6 / TASK-14）
    # ------------------------------------------------------------------
    service_actions: tuple[str, ...] = ("restart", "stop", "start")
    restart_eta_seconds: int = Field(default=150, gt=0)
    #: v0.4 决策 B1：顶栏「服务运行」的刷新间隔（systemctl show 限流）
    service_poll_interval_s: float = Field(default=30.0, gt=0)

    # ------------------------------------------------------------------
    # 告警日志（v0.4.3 §6.1 / TASK-50）
    # ------------------------------------------------------------------
    #: 页面默认展示条数（甲方要求 500 条）
    alert_log_default_limit: int = Field(default=500, ge=1, le=5000)
    #: 内存环形缓冲上限
    alert_log_ring_max: int = Field(default=2000, ge=100)
    #: 落盘文件超过此行数时裁剪（避免无限增长）
    alert_log_file_max: int = Field(default=10000, ge=1000)
    #: 落盘路径；空 = 由 state_dir 推导
    alert_log_path: str = ""

    # ------------------------------------------------------------------
    # 历史服务日志（v0.4.3 §3 / TASK-52）
    # ------------------------------------------------------------------
    #: 可选天数档位（甲方要求 1 / 7 / 30 天）
    log_history_days_options: tuple[int, ...] = (1, 7, 30)
    #: 默认档位（甲方要求 30 天）
    log_history_default_days: int = Field(default=30, ge=1)
    #: 单次查询行数硬上限（实测 30 天约 10,320 行）
    log_history_max_lines: int = Field(default=15000, ge=100)
    #: 单次拉取行数。**必须 >= 最大范围的行数**，否则 journalctl 的 -n 会从
    #: "最旧"一侧截断，导致选 30 天却只覆盖 1 天（实测踩过的坑）。
    #: 前端只渐进渲染前 1000 行，其余靠「加载更多」——传输一次，渲染分批。
    log_history_default_limit: int = Field(default=15000, ge=1)
    #: 查询超时（实测 30 天约 1.19s，留足余量）
    log_history_timeout_s: float = Field(default=30.0, gt=0)
    #: 结果缓存时长，避免反复点档位反复起进程
    log_history_ttl_s: float = Field(default=60.0, ge=0)
    #: 实时日志区保留上限（防止长时间挂机内存增长）
    log_history_live_max_lines: int = Field(default=3000, ge=100)
    #: 是否允许页面开启实时日志（运维可关闭）
    log_history_live_enabled: bool = True

    # ------------------------------------------------------------------
    # 推理框架识别（v0.5 第 1 步）
    # ------------------------------------------------------------------
    #: 识别失败（推理服务未起 / 接口不兼容）时的重试间隔。
    #: 覆盖"先起控制台、后起推理服务"以及"换了框架重启服务"的场景。
    framework_redetect_s: float = Field(default=30.0, gt=0)

    # ------------------------------------------------------------------
    # 事件型告警（v0.4.3）
    # ------------------------------------------------------------------
    #: 日志事件型告警（进程退出 / 上下文截断 / 客户端取消）的保留秒数。
    #: 超过该时长未再发生即自动恢复 —— 否则一次取消会让界面永久挂着告警，
    #: 告警日志也只有 raised 没有 resolved。0 = 不自动恢复（不建议）。
    event_alert_ttl_s: float = Field(default=60.0, ge=0)

    # ------------------------------------------------------------------
    # 多语言（v0.4.3 §4 / TASK-56）
    # ------------------------------------------------------------------
    #: 默认语言策略：auto = 跟随浏览器；zh / en = 固定
    default_lang: str = "auto"
    #: 支持的语言
    supported_langs: tuple[str, ...] = ("zh", "en")
    #: 浏览器语言探测失败时的兜底语言
    lang_fallback: str = "zh"

    # ------------------------------------------------------------------
    # 自身开销守护（方案 TASK-21）
    # ------------------------------------------------------------------
    self_cpu_warn_pct: float = 2.0
    self_rss_warn_mb: float = 200.0
    cmd_slow_ms: float = 400.0

    @field_validator("llama_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # ------------------------------------------------------------------
    @property
    def slots_url(self) -> str:
        return f"{self.llama_base_url}/slots"

    @property
    def props_url(self) -> str:
        return f"{self.llama_base_url}/props"

    @property
    def models_url(self) -> str:
        return f"{self.llama_base_url}/v1/models"

    @property
    def metrics_url(self) -> str:
        return f"{self.llama_base_url}/metrics"

    @property
    def health_url(self) -> str:
        return f"{self.llama_base_url}/health"

    @property
    def journal_cursor_path(self) -> str:
        return str(Path(self.state_dir) / "journal.cursor")

    @property
    def baseline_path(self) -> str:
        return self.baseline_persist_path or str(Path(self.state_dir) / "baseline.json")

    @property
    def hardware_path(self) -> str:
        return self.hw_cache_path or str(Path(self.state_dir) / "hardware.json")

    @property
    def alert_log_resolved_path(self) -> str:
        """告警日志落盘路径（v0.4.3 TASK-50）。"""
        return self.alert_log_path or str(Path(self.state_dir) / "alert_log.jsonl")


_settings: Settings | None = None


def get_settings() -> Settings:
    """进程内单例；测试可用 ``get_settings.cache_clear()`` 复位。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
