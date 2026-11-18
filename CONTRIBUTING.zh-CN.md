# 贡献指南

[English](CONTRIBUTING.md) · **中文**

感谢你愿意为 WKL-LLM运维平台贡献代码。本文档说明如何搭建开发环境、项目遵循的约定，以及提交 PR 的流程。

## 目录

- [行为准则](#行为准则)
- [开发环境](#开发环境)
- [提交前必须通过](#提交前必须通过)
- [代码约定](#代码约定)
- [本项目特有的硬性约束](#本项目特有的硬性约束)
- [提交信息规范](#提交信息规范)
- [Pull Request 流程](#pull-request-流程)
- [报告缺陷](#报告缺陷)

## 行为准则

参与本项目即表示你同意遵守 [行为准则](CODE_OF_CONDUCT.md)。

## 开发环境

需要 **Python 3.12+**，且只支持 **Linux**。本项目面向 Linux：Windows 与 macOS 既不支持部署，
也不支持开发 —— 少量测试与 `mypy` 依赖 Linux 专有能力（`socket.AF_UNIX`、`/proc`），
在其它系统上质量门禁无法通过。

```bash
git clone https://github.com/stevencui581/WKL-LLM-Ops-Platform.git
cd WKL-LLM-Ops-Platform

python3 -m venv venv
./venv/bin/pip install -e '.[dev]'

# 可选：文档导出与远程部署脚本
./venv/bin/pip install -e '.[docs,remote]'
```

也可以直接用安装脚本装完再补开发依赖：

```bash
bash install.sh --skip-deps
./venv/bin/pip install -e '.[dev]'
```

运行控制台：

```bash
export LLMCONSOLE_LLAMA_UNIT=llama-server.service
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8081 --workers 1
```

> **必须 `--workers 1`。** 进程内维护 journalctl 跟随器、WebSocket 广播与硬件缓存，多 worker 会分裂状态。

## 提交前必须通过

```bash
bash selfcheck.sh
```

它依次运行：

| 步骤 | 命令 | 说明 |
| --- | --- | --- |
| 1/4 | `ruff check app tests deploy probes tools` | 规范检查（含 `ASYNC` 规则集） |
| 2/4 | `ruff format --check` | 格式检查 |
| 3/4 | `mypy app` | 类型检查 |
| 4/4 | `pytest` | 单元测试 |

代码**没有格式化**时请运行：

```bash
./venv/bin/ruff check --fix app tests deploy probes tools
./venv/bin/ruff format app tests deploy probes tools
```

如果有文件是在非 Linux 机器上写的（例如 Windows 编辑器），还要跑：

```bash
python tools/fix_line_endings.py
python tools/strip_bom.py
```

> Windows 上的编辑器默认写 CRLF 行尾，而 CRLF 会让 Linux 上的 shell 脚本报
> `set: pipefail: invalid option name`。CI 里有对应守卫。

如果服务已经在运行，还可以跑完整验收：

```bash
bash deploy/verify_all.sh        # 10 套
```

以及前端渲染冒烟（需要 Node）：

```bash
node tools/check_frontend_render.js static
```

## 代码约定

- **注释与文档字符串用中文**，标识符用英文。面向中文运维场景，注释承担"为什么这么写"的职责。
- **`ruff` 的 `ASYNC` 规则集不能关**。它能静态拦截 `async def` 里调用 `subprocess.run`、
  `time.sleep` 这类在运行时完全不可见、只表现为偶发卡顿的错误。
- **新增阈值/常量放到 `app/config.py`**，不要在采集器里散落魔法数字。
- **文案不要写进 JS 代码**。所有面向用户的文字走 `static/i18n.js` 的 `DICT.zh` / `DICT.en`，
  由 `t(key)` 取用；后端下发结构化字段时同时给出中英两份。
- **新增测试优先放在 `tests/`**，写成纯函数级用例；需要真实服务的验证放 `probes/`。

## 本项目特有的硬性约束

这几条是真实事故换来的，PR 若违反会被要求修改：

1. **生产代码里不得出现具体硬件/部署事实**
   不写型号、驱动版本、绝对路径、模型文件名、主机名。全部运行期探测。
   探测失败显示「未知」，接口不存在显示「未安装」，**绝不填默认值**。
   守卫：`tests/test_no_hardcoded_deployment.py`、`tests/test_open_source_compliance.py`。

2. **不得新增图片资源**
   前端保持零图片（无 `<img>`、无 `background-image`、无外部 `url(...)`）。
   守卫：`deploy/check_frontend.py`。

3. **英文文案字典里不得出现中文**
   `DICT.en` 必须无 CJK 字符（唯一豁免：语言切换按钮的 `lang.zh = '中'`）。
   守卫：`tests/test_i18n.py`。

4. **源码扫描类守卫必须先剥离注释**
   注释里的示例代码会让守卫误判（既可能漏报，也可能误报）。
   参考 `tests/test_defect_ledger.py` 的 `_strip_py()`、`_code()`。

5. **不能把渲染结果管道给 `sudo -S`**
   `sudo -S` 从 stdin 读密码，管道内容会被密码提示吃掉，结果写出 0 字节文件，
   systemd 会把它当成 masked。要先写临时文件再 `install`。
   守卫：`tests/test_open_source_compliance.py`。

6. **版本号只有一个来源**
   `app/config.py` 的 `product_version` / `product_name`。前端不得出现版本号字面量
   （页面上的是初始占位，会被 JS 覆盖）。守卫：`tests/test_v043_features.py`。

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<type>(<scope>): <简短描述>

<可选正文：为什么这么改>
```

常用 `type`：

| type | 用途 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 仅文档 |
| `refactor` | 重构（不改行为） |
| `test` | 测试 |
| `chore` | 构建/工具链 |

示例：

```
feat(framework): 支持 SGLang 的版本号自动探测

SGLang 的版本在 /get_server_info 而不是 /version，
原先会识别为「框架已识别但版本未知」。
```

## Pull Request 流程

1. Fork 仓库，从 `main` 切出分支：`git checkout -b fix/kv-eviction`。
2. 修改代码，**补上对应的守卫测试**（缺陷修复必须有回归用例）。
3. 运行 `bash selfcheck.sh`，确保全绿。
4. 提交 PR，填写模板中的检查清单。
5. 维护者会尽快 review；CI 通过是合并的前提。

## 报告缺陷

- 一般缺陷用 [Issue 模板](https://github.com/stevencui581/WKL-LLM-Ops-Platform/issues/new/choose)。
- 报告时请附上：**推理框架与版本**（页面顶部即可看到）、操作系统、Python 版本、
  以及 `journalctl -u <你的控制台服务>` 的相关片段。
- **安全漏洞请不要开公开 Issue**，走 [安全策略](SECURITY.md)。
