# 配置参考

[English](CONFIGURATION.md) · **中文**

全部配置项定义在 **`app/config.py`** 的 `Settings` 类中，通过
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) 加载。

## 配置来源与优先级

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1（最高） | **环境变量** | 前缀 `LLMCONSOLE_`，如 `LLMCONSOLE_LLAMA_UNIT` |
| 2 | **`.env` 文件** | 项目根目录，已被 `.gitignore` 忽略 |
| 3（最低） | `app/config.py` 中的默认值 | 通用默认值，不含任何特定部署事实 |

变量名 = `LLMCONSOLE_` + 字段名大写。嵌套字段用双下划线（`env_nested_delimiter="__"`）。

```bash
# 环境变量写法
export LLMCONSOLE_LLAMA_UNIT=llama-server.service
export LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080
```

```ini
# .env 写法（推荐）
LLMCONSOLE_LLAMA_UNIT=llama-server.service
LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080
LLMCONSOLE_LOG_LEVEL=INFO
```

> 未在 `Settings` 中声明的变量会**直接报错**（`extra="forbid"`）——
> 这是刻意的：避免拼错变量名后静默使用默认值。

---

## 被监控对象

**这是部署时最需要修改的一组。**

| 字段 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `llama_base_url` | `LLMCONSOLE_LLAMA_BASE_URL` | `http://127.0.0.1:8080` | 推理服务 HTTP 地址 |
| `llama_unit` | `LLMCONSOLE_LLAMA_UNIT` | `llm-infer.service` | 被监控的 systemd 单元名 |
| `console_unit` | `LLMCONSOLE_CONSOLE_UNIT` | `llm-console.service` | 控制台自身的单元名（用于自监控） |
| `nvidia_smi` | `LLMCONSOLE_NVIDIA_SMI` | `nvidia-smi` | 命令路径（可指定绝对路径） |
| `rocm_smi` | `LLMCONSOLE_ROCM_SMI` | `rocm-smi` | AMD 显卡工具 |
| `journalctl` | `LLMCONSOLE_JOURNALCTL` | `journalctl` | 日志工具 |
| `systemctl` | `LLMCONSOLE_SYSTEMCTL` | `systemctl` | 服务管理工具 |

**各推理框架的常见取值：**

| 框架 | `LLMCONSOLE_LLAMA_UNIT` | `LLMCONSOLE_LLAMA_BASE_URL` |
| --- | --- | --- |
| llama.cpp | `llama-server.service` | `http://127.0.0.1:8080` |
| Ollama | `ollama.service` | `http://127.0.0.1:11434` |
| vLLM | `vllm.service` | `http://127.0.0.1:8000` |
| SGLang | `sglang.service` | `http://127.0.0.1:30000` |

> 字段名里的 `llama` 是历史命名（项目最初只支持 llama.cpp）。
> **它现在指"被监控的任意推理服务"**，与框架识别结果无关。

---

## 服务监听

| 字段 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `host` | `LLMCONSOLE_HOST` | `0.0.0.0` | 监听地址 |
| `port` | `LLMCONSOLE_PORT` | `8081` | 监听端口 |

> 注意：`uvicorn` 的 `--host` / `--port` 命令行参数优先于这里的配置。

---

## 采集频率与超时

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `poll_interval_s` | `2.0` | 主采集节拍（槽位、指标、GPU） |
| `config_poll_interval_s` | `60.0` | 模型参数轮询（`/props` 变化很慢） |
| `pmon_interval_s` | `10.0` | 进程监控间隔 |
| `http_timeout_s` | `1.0` | 常规 HTTP 超时 |
| `props_timeout_s` | `3.0` | `/props` 超时（处理较慢） |
| `cmd_timeout_s` | `2.0` | 外部命令超时 |
| `cmd_kill_grace_s` | `3.0` | 超时后等待进程退出的宽限 |
| `framework_redetect_s` | `30.0` | **框架识别失败时的重试间隔**（v0.5） |

> 调采集频率前请注意**自身开销**：控制台预算 CPU < 2%、内存 < 200 MB。
> 采集过密会挤占推理服务的资源。

---

## 告警阈值

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `gpu_temp_warn_c` | `83.0` | 显卡温度警告 |
| `gpu_temp_crit_c` | `87.0` | 显卡温度严重 |
| `gpu_temp_sustain_s` | `120.0` | 持续多久才告警（防抖） |
| `vram_warn_pct` | `90.0` | 显存占用警告 |
| `vram_crit_pct` | `95.0` | 显存占用严重 |
| `vram_color_warn_pct` | `85.0` | 卡片变色的阈值（与告警分开） |
| `kv_warn_pct` | `85.0` | KV 容量警告 |
| `kv_crit_pct` | `95.0` | KV 容量严重 |
| `kv_sustain_s` | `60.0` | KV 告警防抖 |
| `power_warn_pct` | `90.0` | 功耗占**该卡自己的** `power_limit` 的比例 |
| `mtp_drop_ratio` | `0.80` | MTP 接受率跌破基线的比例 |
| `mtp_sustain_s` | `300.0` | MTP 告警防抖 |
| `decode_drop_ratio` | `0.50` | 解码吞吐跌破基线的比例 |
| `decode_sustain_s` | `300.0` | 吞吐告警防抖 |
| `service_down_ticks` | `2` | 连续几次探测失败判定服务不可用 |
| `event_alert_ttl_s` | `60.0` | **事件告警自动恢复时长**（0 = 不自动恢复，不建议） |

> **功耗告警是相对值**：按每张卡自己的 `power_limit` 计算，
> 而不是绝对值 —— 不同型号的功耗上限差异很大。

### 基线覆盖（默认自动学习）

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `mtp_accept_baseline` | `None` | `None` = 用自动学习结果；填数值则人工覆盖 |
| `decode_baseline_tps` | `None` | 同上 |

**强烈建议保持 `None`。** 写死基线会导致换机器/换模型后告警持续误报。

---

## 自动基线学习

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `baseline_warmup_s` | `600.0` | 学习前的预热时长 |
| `baseline_min_samples` | `20` | 最少样本数 |
| `baseline_quantile` | `0.50` | 取分位数（0.5 = 中位数） |
| `baseline_persist_path` | `""` | 落盘路径，空 = `state/baseline.json` |
| `baseline_relearn` | `False` | 设为 `True` 会丢弃已学基线重新学习 |

重新学习基线的方法：

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

---

## 硬件与软件栈清点

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `hardware_ttl_s` | `600.0` | 清点结果缓存时长（硬件变化很慢） |
| `hw_cmd_timeout_s` | `3.0` | 单条清点命令超时 |
| `hw_cache_path` | `""` | 缓存路径，空 = `state/hardware.json` |
| `hw_external_python` | `""` | 用指定的 Python 探测 PyTorch 等（用于多环境机器） |
| `hw_enable_smartctl` | `False` | 是否启用 `smartctl` 读硬盘健康（需要 root） |
| `hw_show_launch_args` | `False` | 是否在页面显示推理服务的完整启动参数 |
| `accel_vendor_allowlist` | `("10de", "1002")` | 认可的算力卡 PCI 厂商 ID（NVIDIA / AMD） |
| `accel_pci_denylist` | `("1234:1111",)` | 明确排除的虚拟显卡（QEMU 等） |

### 添加新的算力卡厂家

修改 `accel_vendor_allowlist` 加入新的 PCI 厂商 ID 即可，不需要改代码：

```bash
# 查看机器上的显卡 PCI ID
lspci -nn | grep -iE 'vga|3d|display'
```

```ini
LLMCONSOLE_ACCEL_VENDOR_ALLOWLIST=["10de","1002","1ed5"]
```

> 该字段是元组类型，**环境变量需写成 JSON 数组格式**；改 `.env` 更方便。

### 让控制台看到 conda/其它环境里的 PyTorch

```ini
LLMCONSOLE_HW_EXTERNAL_PYTHON=/opt/conda/bin/python
```

---

## KV 容量判定

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `kv_mode_override` | `""` | 空 = 自动判定；可强制 `"unified"` / `"per_slot"` |
| `kv_quant_show_default` | `True` | 未配置量化时是否显示「f16（默认）」；`False` 则显示「未知」 |

容量模式的判定优先级：**人工覆盖 → 单元文件的 `-kvu` 参数 → `-c` 算术关系 → 日志 → 未知**。

判定不出来时显示「容量模式未知」而不是猜一个 —— 猜错会让 KV 余量完全失真。

---

## 服务管理

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `service_actions` | `("restart", "stop", "start")` | 允许页面触发的动作 |
| `restart_eta_seconds` | `150` | 页面上显示的预估重启耗时 |
| `service_poll_interval_s` | `30.0` | 服务状态轮询间隔（`systemctl show` 有开销，需限流） |

要**完全关闭**服务管理能力，把 `service_actions` 设为空数组：

```ini
LLMCONSOLE_SERVICE_ACTIONS=[]
```

同时不要安装 sudoers 白名单。

---

## 告警日志

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `alert_log_default_limit` | `500` | 页面默认展示条数 |
| `alert_log_ring_max` | `2000` | 内存环形缓冲上限 |
| `alert_log_file_max` | `10000` | 落盘文件裁剪阈值 |
| `alert_log_path` | `""` | 落盘路径，空 = `state/alert_log.jsonl` |

---

## 历史服务日志

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `log_history_days_options` | `(1, 7, 30)` | 页面上的档位按钮 |
| `log_history_default_days` | `30` | 默认档位 |
| `log_history_max_lines` | `15000` | 单次查询行数硬上限 |
| `log_history_default_limit` | `15000` | 单次拉取行数 |
| `log_history_timeout_s` | `30.0` | 查询超时 |
| `log_history_ttl_s` | `60.0` | 结果缓存时长 |
| `log_history_live_max_lines` | `3000` | 实时区保留上限 |
| `log_history_live_enabled` | `True` | 是否允许页面开启实时日志 |

> **`log_history_default_limit` 必须 ≥ 最大档位能产生的行数。**
> 否则 `journalctl -n` 会从"最旧"一侧截断，表现为"选了 30 天却只覆盖 1 天"。
> 这是一个真实踩过的坑，`tests/test_defect_ledger.py::test_d3_*` 有对应守卫。

---

## 多语言

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `default_lang` | `"auto"` | `auto` = 跟随浏览器；`zh` / `en` = 固定 |
| `supported_langs` | `("zh", "en")` | 支持的语言列表 |
| `lang_fallback` | `"zh"` | 浏览器语言探测失败时的兜底 |

语言解析优先级：**`localStorage` 中的手动选择（永久） → `navigator.languages` → 兜底**。

要让所有访问者默认看到英文：

```ini
LLMCONSOLE_DEFAULT_LANG=en
```

---

## 缓冲与背压

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `history_points` | `150` | 图表保留的数据点数（150 点 ≈ 5 分钟） |
| `log_queue_max` | `2000` | 日志入队上限 |
| `log_ring_max` | `1000` | 页面日志环形缓冲 |
| `ws_queue_max` | `100` | 每个 WebSocket 连接的发送队列上限 |
| `ws_send_timeout_s` | `5.0` | WebSocket 发送超时（慢客户端会被断开） |
| `ws_ping_interval_s` | `30.0` | 心跳间隔 |
| `journal_backfill_lines` | `40` | 首次连接的日志回填行数 |
| `journal_since` | `"-7d"` | 首次回填的扫描窗口 |
| `stream_reader_limit` | `1048576` | 流式读取的缓冲上限 |
| `stale_after_misses` | `3` | 连续几次采集失败判定为 stale |

---

## 自身开销守护

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `self_cpu_warn_pct` | `2.0` | 自身 CPU 占用警告线 |
| `self_rss_warn_mb` | `200.0` | 自身内存占用警告线 |
| `cmd_slow_ms` | `400.0` | 外部命令超过此耗时记为慢调用 |

---

## 运行时路径

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `state_dir` | 项目根 `state/` | 状态文件（基线、告警日志、日志游标） |
| `static_dir` | 项目根 `static/` | 前端静态资源 |
| `releases_dir` | 项目根 `releases/` | 发布目录 |

> `state_dir` 在部署时由单元文件通过 `LLMCONSOLE_STATE_DIR` 指定为
> `<部署根>/state`，以便发布切换软链接时状态不丢失。

---

## 品牌与署名

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `product_version` | `v0.5` | **版本号的唯一来源** |
| `product_name` | `WKL-LLM运维平台v0.5` | 顶部标识 |
| `product_name_spaced` | `WKL-LLM运维平台 v0.5` | 带空格的版本 |
| `developer` | `WKL-LLM运维平台` | 底部开发者信息 |
| `develop_date` | `2026.10.01` | 开发日期 |

**为二次开发改名**：只改这几个字段即可，前端会自动跟随（前端没有任何版本号或品牌名硬编码）。

```ini
LLMCONSOLE_PRODUCT_VERSION=v1.0
LLMCONSOLE_PRODUCT_NAME=我的运维平台v1.0
LLMCONSOLE_PRODUCT_NAME_SPACED=我的运维平台 v1.0
LLMCONSOLE_DEVELOPER=某某公司
```

> 守卫 `tests/test_v043_features.py::test_page_scripts_have_no_version_literal`
> 会阻止在前端写死版本号。

---

## 调试

```ini
LLMCONSOLE_LOG_LEVEL=DEBUG
```

日志级别由环境变量 `LLMCONSOLE_LOG_LEVEL` 控制（见 `app/logging_setup.py`）。

框架识别的探测细节会打到 `DEBUG` 级别，用于排查"为什么识别成了 unknown"。
