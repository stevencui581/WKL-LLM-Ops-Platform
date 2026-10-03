# 架构设计

[English](ARCHITECTURE.md) · **中文**

## 设计目标

在**单机**上为本地大模型推理服务提供可读的运行态视图。三个约束决定了整体架构：

1. **零依赖前端** —— 被监控机器往往没有 Node.js，因此前端必须是原生 JS，无构建步骤
2. **单进程** —— 采集状态在进程内共享，避免引入 Redis/消息队列等重型组件
3. **可移植** —— 换框架、换硬件、换机器不需要改代码

## 数据流

```
                     ┌─────────────────────────────────────────────┐
                     │  推理服务（同机）                            │
                     │  llama.cpp / Ollama / vLLM / SGLang         │
                     └───────────────┬─────────────────────────────┘
                                     │
        ┌────────────────────────────┼──────────────────────────────┐
        │                            │                              │
   HTTP API                    Prometheus 文本               systemd / journald
   /props /slots               /metrics                      unit 状态、日志与事件
   /v1/models /health                                        （journalctl 跟随）
        │                            │                              │
        ▼                            ▼                              ▼
 ┌─────────────┐            ┌──────────────┐              ┌────────────────┐
 │ 框架识别     │            │ 指标采集器    │              │ 日志采集器      │
 │ framework.py│            │ prometheus.py│              │ journal.py     │
 └──────┬──────┘            └──────┬───────┘              └───────┬────────┘
        │ 能力清单                  │                              │
        │ （决定下面哪些采集器启用）  │                              │
        └──────────────┬───────────┴──────────────────────────────┘
                       ▼
              ┌────────────────────┐        ┌──────────────────┐
              │ 聚合器 aggregator.py│◄───────│ 硬件清点          │
              │ 并发采集 + 能力裁剪  │        │ hardware.py      │
              └─────────┬──────────┘        │ （nvidia-smi /   │
                        │                   │  lscpu / lsblk…）│
                        ▼                   └──────────────────┘
              ┌────────────────────┐
              │ 告警引擎 alerts.py  │  ← 自动基线 baseline.py
              │ 阈值告警 + 事件告警  │
              │ 含超时自动恢复       │
              └─────────┬──────────┘
                        │
              ┌─────────▼──────────┐
              │ FastAPI 路由        │
              │ REST + WebSocket    │
              └─────────┬──────────┘
                        ▼
              ┌────────────────────┐
              │ 原生 JS 前端        │  中英文由前端选择，后端只给结构化字段
              │ 三个静态页面        │
              └────────────────────┘
```

## 核心模块

### `app/services/framework.py` —— 推理框架识别

**解决的问题**：控制台最初按 llama.cpp 的专有接口（`/props`、`/slots`、`/metrics llamacpp:*`）设计。
换到 Ollama/vLLM/SGLang 时这些端点不存在，界面会大面积空白 + 大量 stale 告警 ——
看起来像控制台坏了，实际只是框架不同。

**做法**：启动时按优先级试探候选端点（先专有信号、后通用兜底），得到
`FrameworkInfo{id, name_zh, name_en, version, capabilities, metrics_prefix}`。

| 框架 | 判定信号 | 版本来源 |
| --- | --- | --- |
| llama.cpp | `/props` 含 `build_info` / `default_generation_settings` / `total_slots` | `/props` → `build_info` |
| Ollama | `/api/version` 含 `version` | `/api/version` |
| SGLang | `/get_model_info` 含 `model_path` / `model_name` | `/get_server_info` |
| vLLM | `/version` 与 `/v1/models` 均可用 | `/version`（纯文本） |
| OpenAI 兼容 | 仅 `/v1/models` 可用 | — |

顺序很重要：llama.cpp、vLLM、SGLang **都**提供 `/v1/models`，
所以专有信号必须排在通用兜底之前，否则会被误判为「OpenAI 兼容」。

识别结果通过 `aggregator.set_framework()` 下发给各采集器，实现**能力裁剪**：
框架没有的接口不再探测、不再计入故障。识别失败时按 `framework_redetect_s` 重试，
覆盖"先起控制台、后起推理服务"的顺序。

**扩展方式**：在 `SPECS` 数据表里加一项即可，不需要写 `if framework == ...`。
守卫测试 `test_no_hardcoded_framework_in_collectors` 会拦住硬编码框架名的写法。

### `app/services/aggregator.py` —— 采集聚合

- **并发采集**：多个数据源并行取数，整体耗时取决于最慢的一个而非求和
  （硬件清点曾在串行下超出 200 ms 预算，改并发后降到约 125 ms）
- **能力裁剪**：根据框架能力开关各采集器
- **事件转告警**：把日志里的事件计数变化转成告警

### `app/collectors/` —— 各数据源

| 采集器 | 数据源 | 备注 |
| --- | --- | --- |
| `slots.py` | `/slots` | 逐槽位上下文、prompt cache；无槽位接口的框架下不启用 |
| `props.py` | `/props`、`/v1/models` | 模型参数与 KV 配置；能力可分别开关 |
| `prometheus.py` | `/metrics` | Prometheus 文本解析；按框架取不同前缀 |
| `gpu.py` | `nvidia-smi` | 温度/功耗/显存/利用率；`[N/A]` 一律转 `None`，不转 0 |
| `hardware.py` | `lscpu`/`lsblk`/`nvidia-smi`/`nvcc` 等 | 全部运行期探测，缺失显示「未安装」 |
| `journal.py` | `journalctl -f` | 跟随推理服务日志，解析事件 |
| `history.py` | `journalctl --since` | 1/7/30 天按需查询 + LRU 缓存 |

### `app/services/alerts.py` —— 告警引擎

两类告警：

- **阈值告警**：与基线比较（KV 占用率、温度、功耗、吞吐偏离）
- **事件告警**：日志中出现特定事件（进程退出、上下文截断、客户端取消）

**关键设计：两类告警都必须能自动恢复。** 事件告警通过 `event_alert_ttl_s` 超时清除，
否则一次客户端取消会让界面永久挂着告警，告警日志也只有 `raised` 没有 `resolved`。

**基线来自自动学习**（`baseline.py`），不是写死的数值：
控制台在服务健康运行时学习 MTP 接受率与解码吞吐，冻结后作为后续告警的比较基准。

### `app/services/alert_log.py` / `alert_catalog.py` —— 告警日志与目录

- `alert_catalog.py`：14 个告警码的中英文名称、级别与分类（数据表驱动）
- `alert_log.py`：环形缓冲（内存 2000 条）+ 落盘（10000 条），
  `sync()` 用**差分语义**判定 `raised` / `resolved`

### 前端（`static/`）

**三层国际化**：

1. HTML 用 `data-i18n` 属性标记文案
2. JS 用 `t(key, params)` 取文案
3. **后端下发结构化字段与语言无关的代码**，前端按当前语言渲染

语言解析优先级：`localStorage`（手动选择，永久） → `navigator.languages` → 兜底 `zh`。

**为什么后端不直接返回中文句子**：那样前端无法切换语言。
后端要么返回代码（如 `progress_code`），要么同时返回中英两份（如 `name: {zh, en}`）。

## 设计原则

### 1. 一切硬件事实都在运行期探测

生产代码里不允许出现具体型号、驱动版本、路径、模型文件名。规则：

| 情况 | 显示 |
| --- | --- |
| 探测成功 | 实际值 |
| 探测失败 | 「未知」 |
| 组件未安装 | 「未安装」 |

**绝不填充默认值**，也绝不猜测。守卫：
`tests/test_no_hardcoded_deployment.py`、`tests/test_open_source_compliance.py`。

### 2. 能力按框架裁剪，而不是报错

框架不提供某接口 → 明确说明「该框架不提供此接口」，
并在日志中记为"能力差异"而非"故障"。这样界面上的「降级」标识才有意义。

### 3. 数据与展示分离

后端下发语言无关的结构化字段，前端决定显示成什么语言。
`en` 字典中不允许出现 CJK 字符（守卫：`tests/test_i18n.py`）。

### 4. 门禁必须可靠

源码扫描类守卫**必须先在匹配前剥离注释**。注释里的示例代码会让守卫误判 ——
既可能漏报（把注释当代码），也可能误报（把示例当违规）。

这条是真实教训：v0.4.4 的 BOM 缺陷之所以危险，正是因为 BOM 让"首行是文档字符串"的判定失效，
整个源码扫描类守卫失去意义。参考实现：
`tests/test_defect_ledger.py` 的 `_strip_py()` / `_code()`。

### 5. 飘红的门禁等于没有门禁

一次性脚本要么删除，要么在 `pyproject.toml` 里**显式豁免并注明原因**。
长期飘红的门禁会让所有人习惯性忽略它。

## 部署模型

```
/opt/WKL-LLM-Ops-Platform/                  ← 部署根目录（可自定义）
├── venv/                          虚拟环境
├── releases/
│   ├── 20261003-001313/           每次发布一个完整目录
│   └── 20261003-002616/           ← 新版本
├── current -> releases/20261003-002616    原子软链接
├── state/                         运行时状态（基线、告警日志、日志游标）
└── logs/
```

发布流程（`deploy/deploy.sh`）：

1. 打包当前代码到 `releases/<时间戳>`
2. 冒烟测试
3. 原子切换 `current` 软链接（`ln -sfnT` + `mv -T`，避免切换瞬间窗口）
4. 重启服务并做健康检查
5. **健康检查失败自动回滚**到上一版本

回滚只需 `bash deploy/rollback.sh`（秒级）。

## 单 worker 的原因

| 组件 | 状态位置 |
| --- | --- |
| journalctl 跟随器 | 进程内的子进程 + 游标文件 |
| WebSocket 广播 | 进程内的连接集合 |
| 硬件清点缓存 | 进程内内存 |
| 基线学习 | 进程内 + 落盘 |

多 worker 会让每个 worker 各自拉一份 journalctl、各自维护连接集合，
既浪费资源又导致数据不一致。采集量本身很小（约 88 MB 内存），单 worker 足够。

## 相关文档

- [安装说明](INSTALL.md)
- [配置参考](CONFIGURATION.md)
- [API 文档](API.md)
- [故障排查](TROUBLESHOOTING.md)
