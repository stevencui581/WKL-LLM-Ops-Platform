# AGENTS.md

给 AI 编码助手（Claude Code、Cursor、Copilot、Codex、DSH 等）的项目约定。
人类贡献者请阅读 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)。

**中文** · [English](AGENTS.md)

---

## 一段话说明项目

**WKL-LLM运维平台** 是面向**本机部署**的大模型推理服务（llama.cpp / Ollama / vLLM / SGLang）
的轻量运维控制台。Python 3.12 + FastAPI 后端，原生 JS 前端（**无构建步骤**），
在 Linux 上以**单进程** + systemd 部署。所有硬件、驱动与框架信息都是**运行期探测**的，
没有任何写死的值。

## 你会用到的命令

```bash
# 质量门禁 —— 提任何改动前都要跑
bash selfcheck.sh                    # ruff check + ruff format --check + mypy + pytest

# 修复格式
./venv/bin/ruff check --fix app tests deploy probes tools
./venv/bin/ruff format app tests deploy probes tools

# 跑单个测试文件
./venv/bin/python -m pytest tests/test_framework.py -q

# 线上验收（需要服务已运行）
bash deploy/verify_all.sh            # 10 套

# 前端渲染冒烟（需要 Node）
node tools/check_frontend_render.js static

# 行尾与 BOM（在 Windows 上改过文件后跑）
python tools/fix_line_endings.py
python tools/strip_bom.py
```

**前端没有构建步骤。** 改完 `static/*.js|html|css` 直接刷新浏览器即可。

## 不可协商的约束

以下条目都有测试守卫，违反会导致 CI 失败。

### 1. 生产代码里不得出现硬件或部署事实

不要把显卡型号、驱动版本、绝对路径、模型文件名、主机名写进
`app/`、`static/`、`deploy/`、`probes/`。

| 情况 | 必须显示 |
| --- | --- |
| 探测成功 | 实际值 |
| 探测失败 | `未知` / `unknown` |
| 组件未安装 | `未安装` / `not installed` |

**绝不填充默认值。** 守卫：`tests/test_no_hardcoded_deployment.py`、
`tests/test_open_source_compliance.py`。

### 2. 前端不得新增图片资源

不允许 `<img>`、`background-image`、外部 `url(...)`。图标用 CSS / Unicode 实现。
守卫：`deploy/check_frontend.py`。

### 3. 双语文案与语言中立的后端

面向用户的文字放 `static/i18n.js`（`DICT.zh` / `DICT.en`），一律通过 `t(key)` 读取。
后端只下发**结构化、语言无关**的字段（代码或 `{zh, en}` 成对值）。
`DICT.en` 中不得出现中文。守卫：`tests/test_i18n.py`。

### 4. `I18N.lang` 必须是取值器

`static/i18n.js` 用 `Object.defineProperty` 导出 `lang`。写成 `lang: LANG` 是**加载时的值拷贝**，
切换语言后其它模块会一直读到旧语言。守卫：`tests/test_snapshot_fields.py`。

### 5. 前端要读的字段必须都在快照里

`MetricSnapshot`（`app/models.py`）就是 `WS /ws/metrics` 广播的内容。页面**每 2 秒被覆盖一次**，
只挂在 REST 路由上的字段会凭空消失。

这造成过一个真实缺陷：顶栏「框架」徽标一直显示「识别中…」，
因为 `framework` 只在 `overview.py` 里加过。守卫：
`tests/test_snapshot_fields.py`、`probes/e2e_ws_snapshot.py`。

### 6. 源码扫描类守卫必须先剥离注释

守卫要先调用 `_strip_py()` / `_code()`（见 `tests/test_defect_ledger.py`）。
注释里的示例代码会同时造成**误报和漏报**。

### 7. 绝不把内容管道给 `sudo -S`

`sudo -S` 从 **stdin** 读密码，管道内容会被密码提示吃掉，目标文件被写成 0 字节 ——
systemd 会把它当成 `masked`。正确做法是先渲染到临时文件，再 `install` / `cp`。

守卫：`tests/test_open_source_compliance.py::test_install_scripts_render_but_do_not_pipe_to_sudo`

### 8. 只用 LF 行尾

CRLF 会破坏 shell 脚本（`set: pipefail: invalid option name`）、
无扩展名的配置文件（sudoers）以及 CSV 夹具。
`.gitattributes` 从 git 层面强制；`tools/fix_line_endings.py` 负责修复。
守卫：`tests/test_open_source_compliance.py::test_no_crlf_line_endings`

### 9. 版本号只有一个来源

`app/config.py` 的 `product_version` / `product_name`。前端不得出现版本号字面量。
守卫：`tests/test_v043_features.py::test_page_scripts_have_no_version_literal`

### 10. 必须单 worker

`--workers 1` 是强制的：进程内持有 journalctl 跟随器、WebSocket 连接集合与硬件缓存。
**不要建议提高 worker 数。**

## 架构导航

| 路径 | 职责 |
| --- | --- |
| `app/services/framework.py` | ★ 运行期框架识别。**数据表驱动**（`SPECS`）—— 加框架是加一行，不是加 `if` |
| `app/services/aggregator.py` | 并发采集、能力裁剪、快照构造 |
| `app/services/alerts.py` | 阈值 + 事件告警，含**自动恢复** |
| `app/services/baseline.py` | 自动学习的 MTP / 解码基线（绝不写死） |
| `app/collectors/` | 每个数据源一个采集器；解析函数是纯函数并有单测 |
| `app/routes/` | REST 端点 |
| `app/main.py` | lifespan、框架识别、采集节拍、WebSocket 路由 |
| `static/app.js` | 主页渲染。所有文案走 `t()` |
| `deploy/` | 部署、回滚、验收脚本（单元文件是**模板**） |
| `probes/` | 线上验收与诊断（针对真实服务运行） |

## 如何新增一个推理框架

1. 在 `app/services/framework.py` 的 `SPECS` 里加一项 `FrameworkSpec`：
   探测路径、版本来源、能力集合、指标前缀、中英说明。
2. 按既有模式在 `tests/test_framework.py` 里加一个假响应测试。
3. 如果需要新能力，在其它 `CAP_*` 旁边加常量，并通过 `aggregator.set_framework()` 门控对应采集器。

**不要**在 `app/collectors/` 里写 `if framework == "x"` ——
守卫 `test_no_hardcoded_framework_in_collectors` 会失败。

## 测试要求

- 每个行为变更都要有测试。
- 每个**缺陷修复**都要有回归用例，并写明**原来的错误判据**是什么。
- 纯逻辑（解析、公式、状态机）→ `tests/`。
- 需要真实服务的 → `probes/`。
- 前端渲染 → `tools/check_frontend_render.js`（Node + 浏览器桩）。

## 完成前

```bash
bash selfcheck.sh
```

必须全绿。在 Windows 上改过文件的话，先跑 `python tools/fix_line_endings.py`。
