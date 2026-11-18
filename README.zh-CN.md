# ⚡ WKL-LLM运维平台

[![CI](https://github.com/stevencui581/WKL-LLM-Ops-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/stevencui581/WKL-LLM-Ops-Platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-v0.6-green.svg)](CHANGELOG.zh-CN.md)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#-硬件与系统要求)

Language: [English](README.md) | 简体中文

面向**本地部署**大模型推理服务的轻量运维控制台 —— 一个页面看清健康、吞吐、KV 缓存与告警。

它把原本要分别去 `nvidia-smi`、`/slots`、`/metrics`、`journalctl` 里看的东西聚合到一个深色主题的
静态页面上，**零前端构建、零图片资源、单进程部署**。所有硬件、驱动与框架信息都是
**运行期探测**的 —— 不写死任何一台机器的型号、路径或模型名。

仓库地址：[stevencui581/WKL-LLM-Ops-Platform](https://github.com/stevencui581/WKL-LLM-Ops-Platform)
当前版本：`v0.6`
版本历史：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)
文档索引：[docs/](docs/README.zh-CN.md)

## 💡 为什么需要它

一台机器上跑 llama.cpp / Ollama / vLLM / SGLang，下面四个问题必须**同时**回答：

- KV 缓存还能撑多少上下文？什么时候会 OOM？
- 显卡有没有撞到温度墙或功耗墙？
- 解码吞吐是否已经偏离这台机器自己的基线？
- 服务退出过吗？上下文被截断过吗？客户端取消过吗？

这些数据散在四个工具、四种输出格式里。本控制台把它们放到一个页面上，
并且**与被监控的推理服务同机运行**，这样才够得着 `systemd` 与 `journald`。

| 原本要手工敲的命令 | 本控制台对应的面板 |
| --- | --- |
| `nvidia-smi` | 显卡温度 / 功耗 / 显存 / 利用率 |
| `/slots` | 逐槽位上下文占用与 prompt cache 命中 |
| `/metrics` | 吞吐、MTP 接受率、token 计数 |
| `journalctl -u <单元>` | 最近日志、1 / 7 / 30 天历史、一键下载 |
| `systemctl status <单元>` | 服务状态、运行时长、重启 / 停止 / 启动 |
| `lscpu`、`lsblk`、驱动检查 | 硬件与软件栈清点 |

## 🧩 支持的推理框架

控制台在启动时自动识别当前框架、版本与可用接口。

| 框架 | 识别依据 | 版本号来源 | 槽位明细 |
| --- | --- | --- | --- |
| **llama.cpp** (`llama-server`) | `/props` 含 `build_info` | `/props` → `build_info` | ✅ `/slots` |
| **Ollama** | `/api/version` | `/api/version` → `version` | ❌ 不提供 |
| **vLLM** | `/version` + `/v1/models` | `/version` | ❌ 不提供 |
| **SGLang** | `/get_model_info` | `/get_server_info` → `version` | ❌ 不提供 |
| OpenAI 兼容服务 | `/v1/models` | — | ❌ 不提供 |
| 未识别 | 所有候选端点均失败 | — | — |

识别结果显示在页面顶部，例如 `框架 llama.cpp b11146`。

**框架不支持某个接口时，控制台会明确说明，而不是显示空白面板或误报"降级"。**
新增框架只需在 `app/services/framework.py` 的 `SPECS` 数据表里加一行 ——
其它地方不允许、也不需要写 `if` 分支。

## 🚀 安装与启动

需要带 **systemd** 的 Linux、**Python 3.12+**，以及与该 Python 版本匹配的 `python3.X-venv` 包
（虚拟环境里的 `pip` 由它提供）。一行命令完成全部安装：

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
```

在同一条命令里指定要监控的推理服务：

```bash
# llama.cpp（端口 8080）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service
```

```bash
# Ollama（端口 11434）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit ollama.service --infer-url http://127.0.0.1:11434
```

```bash
# vLLM（端口 8000）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit vllm.service --infer-url http://127.0.0.1:8000
```

```bash
# SGLang（端口 30000）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit sglang.service --infer-url http://127.0.0.1:30000
```

然后启动：

```bash
cd ~/WKL-LLM-Ops-Platform
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers 1
```

浏览器打开 `http://<服务器地址>:8081`。

> ⚠️ **`--workers 1` 是强制的。** 控制台在进程内维护 journalctl 跟随器、WebSocket 连接集合与
> 硬件缓存；多 worker 会分裂这些状态。单 worker 足以支撑本项目的采集量（约 88 MB 内存）。

要装成开机自启的服务：

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service --install-service -y
```

升级与卸载同样是一行：

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/update.sh | bash
```

```bash
bash uninstall.sh            # 只移除服务，保留代码
bash uninstall.sh --purge    # 全部删除
```

**完整说明 —— 含逐步手动安装与离线安装：** [docs/INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md)

## 🛠️ 硬件与系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | 带 systemd 的 Linux：Ubuntu 22.04+ / Debian 12+ / RHEL 9+ / Fedora 39+ |
| Python | 3.12 或更高 |
| 权限 | 属于 `systemd-journal` 或 `adm` 组（用于读日志） |
| 磁盘 | 约 300 MB |
| 内存 | 约 200 MB 可用；控制台自身约占 88 MB |
| 推理服务 | llama.cpp / Ollama / vLLM / SGLang，**与控制台同机** |

不需要：Docker、Node.js、数据库、反向代理、GPU 驱动、root 权限。

没有显卡也能启动 —— 算力卡面板会如实显示「未检测到」。所有硬件信息都在运行期探测，
换一台机器部署不需要改代码。

## 🧪 质量证据

```bash
bash selfcheck.sh            # ruff check + ruff format --check + mypy + pytest
bash deploy/verify_all.sh    # 10 套端到端验收（需服务已运行）
```

| 项目 | 状态 |
| --- | ---: |
| 单元测试 | 425 项 |
| 端到端验收套件 | 10 套，全通过 |
| 双语文档守卫 | 56 项 |
| 仓库一致性守卫 | 26 项 |
| mypy 检查源文件 | 40 个 |
| 控制台内存占用 | 88 MB（预算 200 MB） |
| 前端构建步骤 | 0 |
| 前端图片资源 | 0 |

## ❓ 常见问题

**支持 Windows 或 macOS 吗？**
不支持。它从 `systemd` 读服务状态、从 `journald` 读日志、从 `nvidia-smi` 读显卡。
你可以在这些平台上开发，但大部分面板会是空的。

**必须和推理服务在同一台机器上吗？**
强烈建议是。只有 HTTP 接口能远程访问；服务状态、日志与显卡数据都不行。

**顶部显示「未识别」怎么办？**
运行 `./venv/bin/python probes/diag_framework_chip.py`。它会打印每个探测路径的 HTTP 状态，
一眼就能看出是地址写错还是端口写错（Ollama 是 11434，vLLM 是 8000，SGLang 是 30000）。

**为什么 Ollama / vLLM / SGLang 没有槽位面板？**
它们不提供槽位接口。这是框架能力差异，不是缺陷 —— 控制台会明确说明，而不是显示一张空表。

**怎么支持你们还不支持的框架？**
在 `app/services/framework.py` 的 `SPECS` 里加一行 `FrameworkSpec` 并补一个假响应测试。
不需要、也不接受写 `if` 分支。

**为什么告警阈值在我的机器上看起来不对？**
很可能是。基线是**按机器自动学习**的，绝不写死。如果基线是在服务被压测时学到的，
删掉 `state/baseline.json` 后重启即可重新学习。

**有登录认证吗？**
没有。这是面向单机内网部署的有意取舍 —— 请在网络层隔离。见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

**为什么只有 30 天日志，有时还更少？**
由你的 journald 保留策略决定。页面报告的是**实际覆盖范围**，不会声称得比真实数据多。

更多：[docs/FAQ.zh-CN.md](docs/FAQ.zh-CN.md) 与 [docs/TROUBLESHOOTING.zh-CN.md](docs/TROUBLESHOOTING.zh-CN.md)

## 🧭 设计原则

1. **一切硬件事实都在运行期探测。** 探测失败显示「未知」，组件缺失显示「未安装」，
   **绝不填充默认值**。
2. **接口能力按框架裁剪。** 换框架应当是"这个接口不采集"，而不是"采集失败、界面降级"。
3. **数据与展示分离。** 后端只下发结构化、语言无关的字段；语言选择权归前端。
4. **门禁必须可靠。** 源码扫描类守卫先剥离注释再匹配 ——
   注释里的示例否则会给出虚假的安全感。
5. **飘红的门禁等于没有门禁。** 一次性脚本要么删除，要么显式豁免并注明原因。

数据流与模块划分见 [docs/ARCHITECTURE.zh-CN.md](docs/ARCHITECTURE.zh-CN.md)。

## 📁 项目结构

```text
WKL-LLM-Ops-Platform/
├── install.sh              一键安装脚本（中英双语输出）
├── update.sh               一键升级（失败自动回滚）
├── uninstall.sh            一键卸载
├── app/                    后端（FastAPI）
│   ├── services/
│   │   ├── framework.py    推理框架自动识别
│   │   ├── aggregator.py   采集聚合与能力裁剪
│   │   └── alerts.py       告警引擎（含自动恢复）
│   ├── collectors/         各数据源采集器（槽位 / 指标 / 硬件 / 日志）
│   └── routes/             REST 与 WebSocket 端点
├── examples/               按框架分好的现成 .env 档案
├── static/                 前端（原生 JS，无构建、无图片）
├── tests/                  单元测试与守卫
├── probes/                 线上验收与诊断探针
├── deploy/                 部署、回滚、验收脚本
├── tools/                  开发辅助工具
└── docs/                   文档（英文 + 中文）
```

## 🤝 贡献

欢迎提交 Issue 与 PR。

- [贡献指南](CONTRIBUTING.zh-CN.md)（[English](CONTRIBUTING.md)）
- [行为准则](CODE_OF_CONDUCT.zh-CN.md)（[English](CODE_OF_CONDUCT.md)）
- [安全策略](SECURITY.zh-CN.md)（[English](SECURITY.md)）—— 安全漏洞请勿开公开 Issue
- [AGENTS.zh-CN.md](AGENTS.zh-CN.md) —— 给 AI 编码助手的项目约定

## 🙏 致谢

- [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) —— README 结构与仓库布局参考
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) ——
  多语言 README 命名与一键安装脚本参考
- [weicj/vLLM-2080Ti-Definitive](https://github.com/weicj/vLLM-2080Ti-Definitive) ——
  排版布局与一键脚本参考
- [OpenJS Foundation](https://github.com/openjs-foundation/cross-project-council) ——
  社区健康文件规范来源
- [Contributor Covenant](https://www.contributor-covenant.org) —— 行为准则来源

## 📄 许可证

[MIT](LICENSE)

---

<sub>开发者信息：WKL-LLM运维平台　　首次发布 2026.10.01　　v0.6</sub>
