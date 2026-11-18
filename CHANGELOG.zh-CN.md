# 更新日志

[English](CHANGELOG.md) · **中文**

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 与
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。

## [未发布]

### 修复

- **安装脚本可能复用残缺的虚拟环境。** 在缺少匹配 `python3.X-venv` 包的发行版上（例如
  Ubuntu 26.04 + Python 3.14），`python3 -m venv` 会留下一个没有 `pip` 的 venv。原先
  `install.sh` 只看到目录存在就「复用」，随后报 `venv/bin/pip: No such file or directory`。
  现在它会检查 `ensurepip`、复用前验证 `pip`、自动重建残缺环境，并统一用 `python -m pip`。
- **多框架的指标从未被采集。** 指标开关每拍都被 `/props` 覆盖，而 vLLM/SGLang 没有 `/props`，
  因此它们的 `/metrics` 从未被读取；同时 series 名被写死成 `llamacpp:*`，`vllm:*` / `sglang:*`
  全被过滤掉。现在开关由框架能力决定，每个框架在 `SPECS` 里声明「概念 → series」映射，
  未映射的概念如实显示不可用而不猜测。

## [v0.6] - 2026-10-04

项目正式仓库地址确定后的首个公开发布版本。除下面的日志分隔行修复外，控制台行为无变化。

### 新增

- `docs/GLOSSARY.md` —— 中文界面与英文代码库之间的术语对照表。
- 全仓版本号与 URL 一致性守卫（`tests/test_repo_consistency.py`）。

### 变更

- 版本号升到 `v0.6`。
- **仓库地址全部改为正式地址** <https://github.com/stevencui581/WKL-LLM-Ops-Platform>。

### 修复

- **journalctl 的启动分隔行没有时间戳。**
  当查询范围**跨重启**时，`journalctl -o short-iso` 会插入
  `-- Boot <id> --` / `-- Reboot --` 分隔行。早期版本把它们当普通日志行返回，后果是
  界面渲染出一行空白时间戳，而且验收探针的 `all(len(ts_local) == 19)` 断言会失败 ——
  **且只在宿主机恰好于查询范围内重启过时才复现**，属于间歇性误报。
  现在 `LogLine` 带 `kind` 字段（`log` / `separator`），分隔行渲染为分隔带。
  回归测试：`tests/test_log_separator.py`。

## [v0.5.1] - 2026-10-04

文档、打包与一键安装。控制台本身的行为无变化。

### 新增

- **一键安装脚本**（`install.sh`）—— 复制一行命令即可：检查系统与依赖 → 下载代码 →
  创建虚拟环境 → 安装依赖 → 生成 `.env` → 自检 → 打印启动命令。
  输出为**中英双语**（自动判断，可用 `WKL_LANG` 强制）。
- **一键升级脚本**（`update.sh`）—— 备份状态 → 拉取代码 → 更新依赖 → 自检 → 重启服务；
  **任一步失败自动回滚**。
- **一键卸载脚本**（`uninstall.sh`）—— `--purge` 可连同代码、虚拟环境、状态一起删除。
- **全量双语文档**：每份文档都有英文（`X.md`）与中文（`X.zh-CN.md`）两个版本，
  遵循 GitHub 命名约定。覆盖 README、安装说明、架构设计、配置参考、API、常见问题、
  故障排查、贡献指南、安全策略、行为准则与更新日志。
- **重写安装说明**，明确分成四段：操作系统要求、依赖环境要求（含全部 Python 依赖）、
  快速安装、逐步手动安装 —— 每一步命令都可直接复制，并给出**预期输出**便于核对。
- `AGENTS.md` —— 给 AI 编码助手的项目约定。
- `.gitattributes` —— 从 git 层面强制 LF 行尾（见「修复」）。
- `.python-version`、`VERSION`、`.env.example`。
- `probes/check_install_scripts.sh` —— 安装脚本的 27 项自检
  （语法、行尾、双语帮助、参数解析）。

### 变更

- README 改为 GitHub 约定：`README.md` 为英文主文档，`README.zh-CN.md` 为中文版；
  删除旧的 `README.en.md`。
- 版本号升到 `v0.5.1`。
- `deploy/upload.py` 现在会上传仓库根的一键脚本，以便在服务器上做语法检查。

### 修复

- **守卫测试自身的缺陷**：`probes/check_install_scripts.sh` 在 `grep -E` 里写了 `\|` ——
  而 `-E` 下 `|` 本就是"或"运算符，`\|` 变成匹配字面量反斜杠加竖线，导致该断言恒失败。
  （由运行守卫本身发现。）

## [v0.5] - 2026-10-03

**首个开源版本。** 从内部交付版本改造为可部署到任意环境的通用项目。

### 新增

- **推理框架自动识别**（`app/services/framework.py`）：运行期识别 llama.cpp、Ollama、vLLM、SGLang
  与 OpenAI 兼容服务，并给出各自的版本号与可用接口清单
  - llama.cpp 版本取自 `/props` → `build_info`（无需执行二进制或翻日志）
  - Ollama 取自 `/api/version`，vLLM 取自 `/version`，SGLang 取自 `/get_server_info`
  - 识别失败按 30 秒间隔重试，覆盖"先起控制台、后起推理服务"的顺序
- **接口能力裁剪**：框架不提供的接口不再反复探测、不再计入故障，界面上明确说明
  "该框架不提供此接口"，而不是显示空白或误报降级
- **页面显示框架与版本**（顶部 `框架` 徽标），中英文均由后端下发
- **开源合规守卫**（`tests/test_open_source_compliance.py`，12 项）：
  行尾 LF、凭据不入库、单元文件模板化、无内网 IP、无本机主路径
- **行尾归一工具**（`tools/fix_line_endings.py`）：修复 Windows 上写出的 CRLF
  （CRLF 会让 Linux 上的 shell 脚本报 `set: pipefail: invalid option name`）
- **部署参数外部化**（`deploy/conn.py` + `deploy/host.env.example`）：
  主机、用户名、密码从环境变量或本地未跟踪文件读取，仓库内零真实凭据
- **systemd 单元模板化**：`__USER__` / `__ROOT__` / `__INFER_UNIT__` 由安装脚本渲染，
  部署到任意用户/目录/推理单元都不需要改文件
- **CI 流水线**（`.github/workflows/ci.yml`）：Python 3.12 上跑 lint、类型检查与测试
- **完整开源配套**：README（中/英）、安装说明、架构设计、配置参考、API 文档、FAQ、
  贡献指南、行为准则、安全策略、Issue/PR 模板

### 变更

- **品牌更名**：原内部名称 → **WKL-LLM运维平台**（英文 **WKL-LLM Ops Platform**）
- 版本号升级至 `v0.5`
- `pyproject.toml` 补齐包元数据（许可证、分类器、关键词、项目链接）
- 上传脚本新增 `--prune` 镜像模式，避免"本地已删、远端还在"

### 移除

- 所有特定部署信息（主机名、内网 IP、用户名、绝对路径、模型文件名）——
  代码、注释、文档、Word 文档内部共清理 1400 余处
- 29 个一次性内部产物（侦察脚本、内部文档流水线、排查脚本）
- `pyproject.toml` 中已失效的 lint 豁免规则

### 修复

- `sudo -S` 与管道冲突导致 systemd 单元文件被写成 0 字节（systemd 视为 `masked`）——
  改为先渲染到临时文件再 `install`
- 源码扫描类守卫被注释中的示例文字误判（与 v0.4.4 的 BOM 缺陷同一失败模式）——
  统一在匹配前剥离注释
- 贪婪正则 `\S*` 在替换时吞掉引号与冒号，破坏 Python 语法

## [v0.4.4] - 2026-10-03

### 新增

- **缺陷回归台账**（`tests/test_defect_ledger.py`，30 项守卫）：把 9 个历史缺陷一项一条固化，
  每条写明原始症状与判据
- **修复现状审计工具**（`probes/audit_defects.py`）：独立交叉校验台账
- 上线预检闭环（`deploy/preflight.py`）：上传 → 远端格式化+门禁 → 回传，杜绝本地/远端分叉

### 修复

- **D9（新发现）**：`sync_from_host.py` 的目录表缺少 `probes`/`tools`，
  导致服务器上的修复无法回传本地、下次上传又被覆盖 —— 表现为"改了没效果"

## [v0.4.3] - 2026-10-02

### 新增

- **告警日志**：保留 500 条，含 `raised` / `resolved` 成对记录，落盘持久化
- **历史服务日志**：1 / 7 / 30 天档位切换、实时跟随、一键下载
- **中英双语**：默认跟随浏览器语言，可手动切换并记忆（"算力卡" → `compute card`）
- 告警目录（14 个告警码，中英文名称与分类）

### 修复

- **D1（自 v0.1 潜伏）**：`CLIENT_CANCEL` 告警从未生效 ——
  取消检测位于 `if not fields: return` 之后，而取消日志行没有其它可解析字段
- **D2**：事件型告警永不恢复 —— 引入 `event_alert_ttl_s` 与超时清除
- **D3**：历史日志"选 30 天只覆盖 1 天" ——
  缓存键缺 `limit` 且路由写死默认值
- **D4**：`spec_types` 字段被字符串替换操作粘连删除
- **D5**：PowerShell 写入 UTF-8 BOM，导致源码守卫失效、shell 脚本无法执行
- **D6**：KV 量化重复标注「（默认）」
- **D7**：历史日志缓存无界增长（46 MB → 88 MB）—— 引入 LRU 淘汰（上限 4 条）
- **D8**：文档生成器给中文插零宽空格，破坏 `中/英切换` 等文本

## [v0.4] - 2026-10-01

### 新增

- **硬件与软件栈清点**：CPU / 内存 / 磁盘 / 驱动 / CUDA / cuDNN / NCCL / PyTorch，
  全部运行期探测，缺失显示「未安装」而非填默认值
- **算力卡厂家适配**：NVIDIA / AMD / 国产加速卡的统一抽象与带宽表
- **自动基线学习**：MTP 接受率与解码吞吐的历史基线自动学习并冻结
- **服务管理**：重启 / 停止 / 启动推理服务，配套最小化 sudo 白名单

### 修复

- 磁盘容量因 systemd 绑定挂载重复计算而虚高 7 倍 —— 改为按**设备**去重
- NVLink 拓扑解析误判：`\bNV\d*\b` 命中了图例文字 —— 改为只解析 GPU 矩阵行
- 硬件清点耗时超出 200 ms 预算（246 ms）—— 改为并发执行，降至 124 ms

## [v0.3.1] - 2026-09-30

### 修复

- 历史日志时间格式与覆盖天数显示
- 静态资源缓存导致的页面不更新

## [v0.3] - 2026-09-30

### 新增

- 实时日志 WebSocket 通道（backfill → 增量）
- 告警阈值可配置化，阈值只允许定义在 `app/config.py`

## [v0.2] - 2026-09-29

### 新增

- 槽位明细与 KV 容量推演
- 算力卡温度、功耗、显存、利用率采集
- Prometheus 指标接入

## [v0.1] - 2026-09-28

### 新增

- 首个版本：FastAPI 后端 + 静态前端，聚合 `nvidia-smi`、`/slots`、`/metrics`、`journalctl`
- 单 worker 部署与 systemd 集成
- 目录化发布 + 原子软链接 + 健康门禁自动回滚

[未发布]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.6...HEAD
[v0.6]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.5.1...v0.6
[v0.5.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.5...v0.5.1
[v0.5]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/releases/tag/v0.5
[v0.4.4]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.4.3...v0.4.4
[v0.4.3]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.4...v0.4.3
[v0.4]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.3.1...v0.4
[v0.3.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.3...v0.3.1
[v0.3]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.2...v0.3
[v0.2]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.1...v0.2
[v0.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/releases/tag/v0.1
