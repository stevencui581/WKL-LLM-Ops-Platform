# 安装说明

**中文** · [English](INSTALL.md) · [项目主页](../README.zh-CN.md) · [配置参考](CONFIGURATION.zh-CN.md) · [常见问题](FAQ.zh-CN.md)

> **本文档的每一条命令都可以直接复制粘贴执行。** 不需要替换占位符的地方已直接给出；
> 需要按你的环境修改的地方用 `<尖括号>` 标出。

## 目录

- [一、安装前的操作系统要求](#一安装前的操作系统要求)
- [二、依赖环境要求](#二依赖环境要求)
- [三、快速安装（推荐）](#三快速安装推荐)
- [四、手动安装（逐步详解）](#四手动安装逐步详解)
- [五、安装后验证](#五安装后验证)
- [六、注册为系统服务（可选）](#六注册为系统服务可选)
- [七、升级](#七升级)
- [八、卸载](#八卸载)
- [九、安装故障速查](#九安装故障速查)

---

## 一、安装前的操作系统要求

### 1.1 支持的系统

| 系统 | 版本 | 状态 |
| --- | --- | --- |
| Ubuntu | 22.04 / 24.04 LTS | ✅ 官方测试 |
| Debian | 12 (Bookworm) 及以上 | ✅ 官方测试 |
| Rocky Linux / AlmaLinux / RHEL | 9 及以上 | ✅ 支持 |
| Fedora | 39 及以上 | ✅ 支持 |
| openEuler / 麒麟 / 统信 UOS | 较新版本 | ⚠️ 未全面测试，通常可用 |
| 其它带 systemd 的 Linux | — | ⚠️ 未测试，通常可用 |
| **Windows / macOS** | — | ❌ **不支持部署** |

> **为什么必须 Linux**：本平台通过 `systemd` 读取推理服务的运行状态、通过 `journald`
> 读取服务日志、通过 `nvidia-smi` 读取显卡信息。这三项在 Windows / macOS 上不存在。
>
> 但你**可以在 Windows / macOS 上开发**：单元测试不依赖这些命令，只是跑起来后大部分面板会显示「未检测到」。

### 1.2 硬性前提

| 项目 | 要求 | 检查命令 |
| --- | --- | --- |
| init 系统 | **systemd**（必需） | `systemctl --version` |
| 权限 | 能读 journald（`systemd-journal` 或 `adm` 组成员） | `id -nG \| tr ' ' '\n' \| grep -E 'systemd-journal\|adm'` |
| 网络 | 能访问 PyPI（离线安装见 §4.4） | `curl -I https://pypi.org` |
| 磁盘 | 约 **300 MB**（虚拟环境 + 代码 + 状态文件） | `df -h .` |
| 内存 | 约 **200 MB** 可用（平台自身占用约 88 MB） | `free -m` |

**检查你的系统是否满足（复制执行）：**

```bash
# 系统与内核
uname -s && grep -E '^(NAME|VERSION)=' /etc/os-release

# systemd 是否存在
systemctl --version | head -1

# 是否在 journald 可读组里
id -nG | tr ' ' '\n' | grep -E '^(systemd-journal|adm)$' && echo "✅ 日志可读" || echo "⚠️ 需要加入组（见下）"

# 磁盘与内存
df -h . | tail -1
free -m | head -2
```

**如果提示日志不可读**（日志面板会是空的）：

```bash
sudo usermod -aG systemd-journal "$USER"
# 然后退出登录并重新登录（或重启），组权限才会生效
```

### 1.3 不需要的东西（常见误解）

| 不需要 | 说明 |
| --- | --- |
| ❌ Docker / Kubernetes | 单进程部署，直接跑在宿主机上 |
| ❌ Node.js | 前端是原生 JavaScript，**零构建步骤** |
| ❌ Nginx / 反向代理 | 平台自带 HTTP 服务；可选配代理加认证 |
| ❌ 数据库 | 状态存本地 JSON / JSONL 文件 |
| ❌ GPU 驱动 | 没有显卡也能启动，只是算力卡面板显示「未检测到」 |
| ❌ root 权限 | 安装不需要 root；只有注册系统服务时才需要 sudo |

---

## 二、依赖环境要求

### 2.1 必需依赖（缺一不可）

| 依赖 | 版本要求 | 用途 | 缺失后果 |
| --- | --- | --- | --- |
| **Python** | **≥ 3.12** | 运行后端 | 无法启动 |
| **python3-venv** | 与 Python 同版本 | 创建虚拟环境 | 无法隔离依赖 |
| **pip** | ≥ 22 | 安装依赖 | 无法安装 |
| **systemd** | 任意较新版本 | 服务状态、开机自启 | 无法读取推理服务状态 |
| **journalctl** | 随 systemd | 读取服务日志 | 日志面板为空 |
| **git** | 任意 | 获取代码（也可用压缩包替代） | 无法 clone |

### 2.2 Python 依赖包（安装脚本会自动装）

运行时依赖定义在 `pyproject.toml`：

| 包 | 版本要求 | 作用 |
| --- | --- | --- |
| `fastapi` | ≥ 0.115 | Web 框架 |
| `uvicorn[standard]` | ≥ 0.30 | ASGI 服务器（含 WebSocket 支持） |
| `httpx` | ≥ 0.27 | 访问推理服务 HTTP 接口 |
| `psutil` | ≥ 5.9 | 进程与系统信息采集 |
| `pydantic-settings` | ≥ 2.4 | 配置管理 |

**可选依赖**（不装不影响使用）：

| 包 | 安装方式 | 作用 |
| --- | --- | --- |
| `python-docx` | `pip install -e '.[docs]'` | Markdown → Word 文档导出 |
| `paramiko` | `pip install -e '.[remote]'` | 从另一台机器远程部署 |
| `pytest` `ruff` `mypy` 等 | `pip install -e '.[dev]'` | 开发与测试 |

### 2.3 外部命令（按需，缺失只影响对应面板）

| 命令 | 提供者 | 影响的模块 |
| --- | --- | --- |
| `nvidia-smi` | NVIDIA 驱动 | 算力卡温度 / 功耗 / 显存 / 利用率 |
| `rocm-smi` | AMD ROCm | AMD 显卡信息 |
| `lscpu` `lsblk` `free` | util-linux / procps | 硬件清点（几乎都有） |
| `nvcc` | CUDA Toolkit | CUDA 版本（也可从 `version.json` 读） |
| `smartctl` | smartmontools | 硬盘健康（默认关闭） |

> **这些命令缺失不是错误。** 平台的规则是：**探测成功显示实际值，探测失败显示「未知」，
> 组件未安装显示「未安装」—— 绝不填充默认值。**

### 2.4 一键检查依赖（复制执行）

```bash
echo "== Python =="; for p in python3.13 python3.12 python3; do command -v $p >/dev/null && echo "  $p -> $($p -V 2>&1)"; done
echo "== venv =="; python3 -c 'import venv; print("  ✅ venv 可用")' 2>/dev/null || echo "  ❌ venv 缺失"
echo "== pip =="; python3 -m pip --version 2>/dev/null || echo "  ❌ pip 缺失"
echo "== systemd =="; systemctl --version 2>/dev/null | head -1 || echo "  ❌ 无 systemd（不支持）"
echo "== git =="; git --version 2>/dev/null || echo "  ⚠️ 无 git（可用压缩包替代）"
echo "== nvidia-smi =="; nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -3 || echo "  ⚠️ 未安装（只影响算力卡面板）"
```

### 2.5 补齐缺失的依赖

**Ubuntu / Debian：**

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git util-linux procps curl
```

**Rocky / AlmaLinux / RHEL / Fedora：**

```bash
sudo dnf install -y python3.12 python3.12-pip git util-linux procps-ng curl
```

**openEuler / 麒麟 / 统信（yum 系）：**

```bash
sudo yum install -y python3 python3-pip git util-linux procps-ng curl
```

> **你的发行版仓库里没有 Python 3.12？** 三种办法：
> 1. `deadsnakes`（Ubuntu）：`sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv`
> 2. `uv` 一键装：`curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12`
> 3. 源码编译：<https://www.python.org/downloads/>

---

## 三、快速安装（推荐）

### 3.1 最短路径：一行命令

**复制下面这一行，粘贴到终端回车即可：**

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
```

脚本会自动完成：检查系统 → 检查依赖 → 下载代码 → 创建虚拟环境 → 安装依赖 → 生成配置 → 自检，
并在最后**打印出启动命令**。

**如果已经 clone 了仓库：**

```bash
cd WKL-LLM-Ops-Platform && bash install.sh
```

### 3.2 指定推理服务（推荐做法）

安装时告诉它要监控哪个推理服务，后面就不用改配置文件：

```bash
# llama.cpp（默认端口 8080）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service

# Ollama（默认端口 11434）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit ollama.service --infer-url http://127.0.0.1:11434

# vLLM（默认端口 8000）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit vllm.service --infer-url http://127.0.0.1:8000

# SGLang（默认端口 30000）
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit sglang.service --infer-url http://127.0.0.1:30000
```

不知道单元名？先查一下：

```bash
systemctl list-units --type=service --state=running \
  | grep -iE 'llama|ollama|vllm|sglang|infer'
```

### 3.3 安装并注册为系统服务（开机自启）

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service --install-service -y
```

> 注册服务需要 sudo 权限。脚本会调用 `deploy/install_service.sh`，
> 自动把单元文件模板里的 `__USER__` / `__ROOT__` / `__INFER_UNIT__`
> 按你当前的环境渲染后写入 `/etc/systemd/system/`。

### 3.4 安装脚本的全部参数

```bash
bash install.sh --help
```

| 参数 | 说明 |
| --- | --- |
| `--port <端口>` | 控制台监听端口（默认 8081） |
| `--infer-unit <单元名>` | 被监控的推理服务 systemd 单元 |
| `--infer-url <URL>` | 推理服务 HTTP 地址 |
| `--install-service` | 同时注册 systemd 服务（需要 sudo） |
| `--skip-deps` | 跳过依赖安装（离线环境） |
| `-y, --yes` | 非交互模式，全部用默认值 |
| `-h, --help` | 显示帮助 |

环境变量：`WKL_LANG=zh|en`（强制语言）、`WKL_PORT`、`WKL_INFER_UNIT`、`WKL_INFER_URL`、`WKL_INSTALL_DIR`、`SUDO_PW`。

### 3.5 启动

```bash
cd ~/WKL-LLM-Ops-Platform                     # 或你指定的安装目录
./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1
```

浏览器打开 `http://<服务器地址>:8081`。

> ⚠️ **`--workers 1` 是强制的。** 平台在进程内维护 journalctl 跟随器、WebSocket 广播与硬件缓存，
> 多 worker 会导致状态分裂。

---

## 四、手动安装（逐步详解）

不想用脚本、或脚本在受限环境里跑不通时，按下面的步骤做。
**每一步都有「预期输出」，对不上就说明这一步骤没成功。**

### 4.1 准备目录并获取代码

```bash
# 1) 选一个安装目录（示例：当前用户主目录）
cd "$HOME"

# 2) 获取代码（二选一）
git clone https://github.com/stevencui581/WKL-LLM-Ops-Platform.git
cd WKL-LLM-Ops-Platform
```

**没有 git 的话**，用压缩包：

```bash
curl -fsSL https://github.com/stevencui581/WKL-LLM-Ops-Platform/archive/refs/heads/main.tar.gz -o wkl.tar.gz
tar -xzf wkl.tar.gz
mv WKL-LLM-Ops-Platform-main WKL-LLM-Ops-Platform
cd WKL-LLM-Ops-Platform
```

**预期输出**：`ls` 能看到 `app/ static/ tests/ deploy/ pyproject.toml install.sh` 等。

```bash
ls
```

### 4.2 确认 Python 版本 ≥ 3.12

```bash
python3 -V
```

**预期输出**：`Python 3.12.x` 或更高。

如果 `python3 -V` 低于 3.12，但机器上装了 `python3.12`：

```bash
python3.12 -V
# 后面所有 python3 都换成 python3.12
```

**批量检查候选版本：**

```bash
for p in python3.13 python3.12 python3; do
  command -v $p >/dev/null 2>&1 && echo "$p -> $($p -V 2>&1)"
done
```

### 4.3 创建虚拟环境

```bash
python3 -m venv venv
```

**预期输出**：无输出即为成功；当前目录会多出 `venv/` 目录。

```bash
ls -d venv && echo "✅ 虚拟环境已创建"
```

**若报错 `No module named venv`**：

```bash
sudo apt install -y python3.12-venv     # Ubuntu / Debian
sudo dnf install -y python3.12-pip      # RHEL 系
```

### 4.4 安装依赖

```bash
# 升级 pip（可选但推荐）
./venv/bin/python -m pip install --upgrade pip

# 安装运行时依赖
./venv/bin/pip install -e .
```

**预期输出**：最后一行是
`Successfully installed fastapi-... uvicorn-... httpx-... psutil-... pydantic-settings-...`

**网络慢或被墙**，换国内镜像：

```bash
./venv/bin/pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**离线 / 内网环境**：在有网的机器上下载全部 wheel，拷到目标机：

```bash
# 有网的机器（与目标机同架构同 Python 版本）
pip download -d ./wheels -e .
# 目标机器
./venv/bin/pip install --no-index --find-links=./wheels -e .
```

**若报 `error: command 'gcc' failed`**（少数包需要编译）：

```bash
sudo apt install -y build-essential python3-dev     # Ubuntu / Debian
sudo dnf install -y gcc python3-devel               # RHEL 系
```

### 4.5 写入配置

按框架分好的现成档案（llama.cpp / Ollama / vLLM / SGLang）在
[`examples/`](../examples/README.md) —— 复制一份、改掉单元名即可：

```bash
cp examples/llama-cpp.env .env
```

也可以手写 `.env`：

```bash
cat > .env <<'EOF'
# 被监控的推理服务 systemd 单元名（按你的实际情况改）
LLMCONSOLE_LLAMA_UNIT=llama-server.service

# 推理服务 HTTP 地址
#   llama.cpp  http://127.0.0.1:8080
#   Ollama     http://127.0.0.1:11434
#   vLLM       http://127.0.0.1:8000
#   SGLang     http://127.0.0.1:30000
LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080

# 控制台监听端口
LLMCONSOLE_PORT=8081

# 日志级别：DEBUG / INFO / WARNING
LLMCONSOLE_LOG_LEVEL=INFO
EOF
```

**预期输出**：`cat .env` 能看到上面内容。

```bash
cat .env
```

> `.env` 已在 `.gitignore` 中，**不会被提交到仓库**。
> 全部可调参数见 [配置参考](CONFIGURATION.zh-CN.md)。

### 4.6 验证安装

```bash
./venv/bin/python -c "import app.main; print('✅ 后端可导入')"
```

**预期输出**：`✅ 后端可导入`

```bash
./venv/bin/python -c "from app.config import Settings; s=Settings(); print(s.product_name, s.product_version)"
```

**预期输出**：`WKL-LLM运维平台v0.6 v0.6`

### 4.7 启动

**前台启动（便于看日志、排查问题）：**

```bash
./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1 \
  --no-access-log --timeout-graceful-shutdown 30
```

**预期输出**（关键两行）：

```
INFO:     Uvicorn running on http://0.0.0.0:8081 (Press CTRL+C to quit)
INFO [main] framework: llama.cpp b11146 [health,metrics,models,props,slots]
```

第二行说明**推理框架识别成功**。如果显示 `unknown`，见 [故障排查](TROUBLESHOOTING.zh-CN.md)。

**后台启动（临时用）：**

```bash
mkdir -p logs
nohup ./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1 \
  > logs/console.log 2>&1 &
```

> 长期运行请用 systemd 方式（见 §6）—— `nohup` 不会开机自启也不会自动重启。

---

## 五、安装后验证

复制执行，四项都应返回 `200`：

```bash
curl -s -o /dev/null -w 'live     = %{http_code}\n' http://127.0.0.1:8081/api/health/live
curl -s -o /dev/null -w 'ready    = %{http_code}\n' http://127.0.0.1:8081/api/health/ready
curl -s -o /dev/null -w 'overview = %{http_code}\n' http://127.0.0.1:8081/api/overview
curl -s -o /dev/null -w 'index    = %{http_code}\n' http://127.0.0.1:8081/
```

**看框架识别结果（最关键的一项）：**

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | ./venv/bin/python -c 'import json,sys; f=json.load(sys.stdin)["framework"]; print("框架:", f["id"], f["version"], f["capabilities"])'
```

**预期输出**：`框架: llama.cpp b11146 ['health', 'metrics', 'models', 'props', 'slots']`

**跑内置诊断（推荐）：**

```bash
./venv/bin/python probes/check_branding.py        # 品牌与版本一致性
./venv/bin/python probes/diag_framework_chip.py   # 框架识别链路
./venv/bin/python deploy/check_frontend.py        # 前端静态自检
```

---

## 六、注册为系统服务（可选）

需要 sudo。**单元名按你的实际推理服务改**：

```bash
LLM_INFER_UNIT=llama-server.service \
SUDO_PW='<你的sudo密码>' \
  bash deploy/install_service.sh
```

sudo 不需要密码时可以省略 `SUDO_PW`。

脚本会：创建 `state/` `logs/` `releases/` → 渲染单元模板 → `systemd-analyze verify`
→ `daemon-reload` → `enable` → `restart` → 探测健康端点 → 输出安全评分。

**查看状态与日志：**

```bash
systemctl status llm-console.service
journalctl -u llm-console.service -f
```

### 可选：允许从页面重启推理服务

平台默认**只能只读查看**推理服务状态。要允许页面上的重启/停止按钮，需安装最小化 sudo 白名单：

```bash
SUDO_PW='<你的sudo密码>' LLM_INFER_UNIT=llama-server.service \
  bash deploy/install_sudoers.sh
```

白名单**只放行被监控单元的四个动作**（restart / stop / start / reset-failed），
不放行任意 systemctl 命令。**不需要就不要装**，只读更安全。
详见 [安全策略](../SECURITY.zh-CN.md)。

---

## 七、升级

**一行命令：**

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/update.sh | bash
```

**已 clone 的仓库：**

```bash
cd WKL-LLM-Ops-Platform && bash update.sh
```

脚本会：备份 `state/` `logs/` `.env` → `git pull` → 更新依赖 → 自检 → 重启服务。
**任何一步失败会自动回滚**到升级前的版本。

手动升级：

```bash
cd WKL-LLM-Ops-Platform
git pull
./venv/bin/pip install -e .
sudo systemctl restart llm-console.service     # 若已注册服务
```

> 平台还带**目录化发布 + 原子软链接 + 健康门禁自动回滚**的部署方式：
> `bash deploy/deploy.sh` 发布新版本，`bash deploy/rollback.sh` 秒级回滚。
> 详见 [架构设计](ARCHITECTURE.zh-CN.md)。

---

## 八、卸载

```bash
# 只移除服务（保留代码与配置）
bash uninstall.sh

# 连同代码、虚拟环境、状态一起删除
bash uninstall.sh --purge
```

手动卸载：

```bash
SUDO_PW='<密码>' bash deploy/install_sudoers.sh --remove   # 若装过白名单
sudo systemctl disable --now llm-console.service
sudo rm -f /etc/systemd/system/llm-console.service
sudo systemctl daemon-reload
rm -rf ~/WKL-LLM-Ops-Platform          # 确认路径无误后再执行
```

---

## 九、安装故障速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Python 3.12 or newer is required` | Python 版本过低 | 见 [§2.5](#25-补齐缺失的依赖) |
| `No module named venv` | 缺 python3-venv | `sudo apt install -y python3.12-venv` |
| `pip install` 超时 | 网络问题 | 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `error: command 'gcc' failed` | 缺编译工具 | `sudo apt install -y build-essential python3-dev` |
| `Address already in use` | 8081 被占用 | `ss -lntp \| grep 8081` 或改 `LLMCONSOLE_PORT` |
| 页面能开但数据全是「—」 | 推理服务地址/单元名不对 | 检查 `.env` 里的 `LLMCONSOLE_LLAMA_BASE_URL` 与 `LLMCONSOLE_LLAMA_UNIT` |
| 顶部「框架」显示未识别 | 探测端点不通 | `./venv/bin/python probes/diag_framework_chip.py` |
| 日志面板为空 | 无 journald 读权限 | `sudo usermod -aG systemd-journal $USER` 后重新登录 |
| `set: pipefail: invalid option name` | 脚本被写成了 CRLF 行尾 | 重新 clone；不要用 Windows 编辑器改 `.sh` |
| systemd 显示 `masked` | 单元文件被写成 0 字节 | `bash deploy/install_service.sh` 重装（仓库脚本已修复该问题） |

**还有问题？** 见 [故障排查](TROUBLESHOOTING.zh-CN.md) 与 [常见问题](FAQ.zh-CN.md)，
或在 [Issues](https://github.com/stevencui581/WKL-LLM-Ops-Platform/issues) 提问。

---

**下一步：** [配置参考](CONFIGURATION.zh-CN.md) · [架构设计](ARCHITECTURE.zh-CN.md) · [API 文档](API.zh-CN.md)
