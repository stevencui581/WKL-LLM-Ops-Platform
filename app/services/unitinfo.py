"""从 systemd unit 读取 llama-server 的真实运行参数（方案 TASK-05 / 6.4.4）。

为什么需要这个模块：
  * ``/props`` 的 ``default_generation_settings.params`` 只是**默认值**，
    实测 ``speculative.types`` 报 ``"none"``，并不代表真实配置；
  * ``/slots`` 的 ``params`` 只在槽位有任务时才有值，空闲时全为 ``None``；
  * 唯一权威来源是 systemd unit 的 ``ExecStart``。

实测踩坑记录：仅靠 /props + /slots，空闲服务器上「投机解码」徽标会显示成
``none``，与真实的 ``--spec-type draft-mtp`` 不符。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 各参数的匹配规则（短选项与长选项都覆盖）
RE_SPEC_TYPE = re.compile(r"--spec-type\s+(\S+)")
RE_DRAFT_MAX = re.compile(r"--spec-draft-n-max\s+(\d+)")
RE_FLASH = re.compile(r"(?:^|\s)(?:-fa|--flash-attn)\s+(on|off|auto)")
RE_TENSOR_SPLIT = re.compile(r"(?:^|\s)(?:-ts|--tensor-split)\s+(\S+)")
RE_PARALLEL = re.compile(r"(?:^|\s)(?:--parallel|-np)\s+(\d+)")
RE_CTX = re.compile(r"(?:^|\s)(?:-c|--ctx-size)\s+(\d+)")
RE_MODEL = re.compile(r"(?:^|\s)(?:-m|--model)\s+(\S+)")
RE_NGL = re.compile(r"(?:^|\s)(?:-ngl|--n-gpu-layers)\s+(\d+)")
RE_METRICS = re.compile(r"(?:^|\s)--metrics(?:\s|$)")
#: v0.4 TASK-46：KV 布局与量化类型（F17）
RE_KV_UNIFIED = re.compile(r"(?:^|\s)(?:-kvu|--kv-unified)(?:\s|$)")
RE_SPLIT_MODE = re.compile(r"(?:^|\s)(?:-sm|--split-mode)\s+(\S+)")
RE_CACHE_K = re.compile(r"(?:^|\s)(?:-ctk|--cache-type-k)\s+(\S+)")
RE_CACHE_V = re.compile(r"(?:^|\s)(?:-ctv|--cache-type-v)\s+(\S+)")


@dataclass
class UnitConfig:
    spec_type: str = ""
    draft_n_max: int = 0
    flash_attn: bool | None = None
    tensor_split: str = ""
    parallel: int = 0
    n_ctx: int = 0
    model_path: str = ""
    n_gpu_layers: int = 0
    metrics_flag: bool = False
    #: v0.4：统一 KV 池开关（-kvu）；None = unit 不可读、无从判断
    kv_unified: bool | None = None
    #: v0.4：切分模式（-sm tensor / layer / row）
    split_mode: str = ""
    #: v0.4：KV 量化类型；空串 = 未配置（llama.cpp 用默认 f16）
    cache_type_k: str = ""
    cache_type_v: str = ""
    unit: str = ""
    raw_exec: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def gpu_count(self) -> int:
        """从 tensor-split 推断卡数（如 ``1,1`` -> 2）。"""
        if not self.tensor_split:
            return 0
        parts = [p for p in self.tensor_split.split(",") if p.strip()]
        return len(parts)

    @property
    def tensor_parallel(self) -> bool:
        """是否启用张量并行（v0.4 R1 顶栏标识1 用）。"""
        return self.split_mode == "tensor"

    @property
    def readable(self) -> bool:
        """unit 是否读到内容 —— 用于区分「探测不到」与「确认不存在」（P3）。"""
        return bool(self.raw_exec)

    @property
    def cache_type(self) -> tuple[str, str]:
        """返回 (K, V) 量化类型；未配置时为空串。"""
        return (self.cache_type_k, self.cache_type_v)


def _int(m) -> int:
    try:
        return int(m.group(1))
    except (AttributeError, ValueError, TypeError):
        return 0


def parse_unit_text(text: str, unit: str = "") -> UnitConfig:
    """从 unit 文件内容解析 ExecStart。解析失败一律返回默认值，不抛异常。"""
    cfg = UnitConfig(unit=unit)
    if not text:
        return cfg
    # 只取 ExecStart（可能跨行续行）
    lines = text.splitlines()
    exec_lines: list[str] = []
    collecting = False
    for ln in lines:
        if ln.startswith("ExecStart="):
            collecting = True
            exec_lines.append(ln[len("ExecStart=") :])
            continue
        if collecting:
            if ln.startswith((" ", "\t")) or ln.rstrip().endswith("\\"):
                exec_lines.append(ln)
                continue
            break
    exec_text = " ".join(exec_lines).replace("\\", " ")
    cfg.raw_exec = " ".join(exec_text.split())
    if not cfg.raw_exec:
        return cfg

    m = RE_SPEC_TYPE.search(exec_text)
    if m:
        cfg.spec_type = m.group(1)
    cfg.draft_n_max = _int(RE_DRAFT_MAX.search(exec_text))
    m = RE_FLASH.search(exec_text)
    if m:
        cfg.flash_attn = m.group(1) in ("on", "auto")
    m = RE_TENSOR_SPLIT.search(exec_text)
    if m:
        cfg.tensor_split = m.group(1)
    cfg.parallel = _int(RE_PARALLEL.search(exec_text))
    cfg.n_ctx = _int(RE_CTX.search(exec_text))
    m = RE_MODEL.search(exec_text)
    if m:
        cfg.model_path = m.group(1)
    cfg.n_gpu_layers = _int(RE_NGL.search(exec_text))
    cfg.metrics_flag = bool(RE_METRICS.search(exec_text))
    # v0.4 TASK-46
    cfg.kv_unified = bool(RE_KV_UNIFIED.search(exec_text))
    m = RE_SPLIT_MODE.search(exec_text)
    if m:
        cfg.split_mode = m.group(1)
    m = RE_CACHE_K.search(exec_text)
    if m:
        cfg.cache_type_k = m.group(1)
    m = RE_CACHE_V.search(exec_text)
    if m:
        cfg.cache_type_v = m.group(1)
    return cfg


def read_unit(unit: str, directories: tuple[str, ...] | None = None) -> UnitConfig:
    """从磁盘读取 unit 文件；读不到返回空配置。"""
    dirs = directories or ("/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system")
    for d in dirs:
        path = f"{d.rstrip('/')}/{unit}"
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return parse_unit_text(f.read(), unit)
        except OSError:
            continue
    return UnitConfig(unit=unit)
