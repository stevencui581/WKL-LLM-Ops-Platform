# 常见问题

[English](FAQ.md) · **中文**

## 安装与部署

### 支持 Windows 或 macOS 部署吗？

**不支持。** 控制台依赖 systemd 与 journald 读取服务状态和日志，
并用 `nvidia-smi` / `lscpu` / `lsblk` 做硬件清点。这些在 Windows/macOS 上不存在。

**但可以在 Windows/macOS 上开发**：单元测试不需要这些命令（采集器都有纯函数级的解析测试）。
只是跑起来后大部分面板会显示「未检测到」。

### 必须和推理服务在同一台机器上吗？

**强烈建议是。** 控制台通过以下方式取数：

- 推理服务的 HTTP 接口（可以远程）
- `systemd` 单元状态（**必须同机**）
- `journalctl` 日志（**必须同机**）
- `nvidia-smi` 显卡信息（**必须同机**）

跨机部署时后三项会全部失效，控制台退化成"只能看 HTTP 指标"。

### 为什么必须 `--workers 1`？

控制台在**进程内**维护四类状态：

| 状态 | 说明 |
| --- | --- |
| journalctl 跟随器 | 一个子进程 + 游标文件 |
| WebSocket 广播 | 连接集合 |
| 硬件清点缓存 | 内存 |
| 基线学习 | 内存 + 落盘 |

多 worker 会让每个 worker 各自拉一份 journalctl、各自维护连接集合 ——
既浪费资源，又让页面数据不一致（不同请求打到不同 worker）。

采集量本身很小（约 88 MB 内存），单 worker 完全够用。

### 端口 8081 被占用了怎么办？

改配置即可：

```ini
LLMCONSOLE_PORT=9090
```

但要注意：`uvicorn` 的 `--port` 命令行参数**优先于**这个配置。
用 systemd 部署时两处都在单元文件里（`ExecStart` 的 `--port` 和 `Environment`）。

---

## 推理框架识别

### 顶部「框架」显示"未识别"怎么办？

说明所有候选端点都没探通。按顺序排查：

```bash
# 1. 推理服务在跑吗？
systemctl status <你的推理服务>

# 2. HTTP 地址对吗？（默认 8080，Ollama 是 11434，vLLM 是 8000）
curl -s http://127.0.0.1:8080/health

# 3. 看控制台的探测详情（每个路径的 HTTP 状态）
journalctl -u llm-console.service -n 50 | grep -i framework
```

`/api/overview` 的 `framework.probes` 会列出每个探测路径的状态码，能直接看出哪个通了、哪个 404。

**常见原因：**

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 所有路径都失败 | HTTP 地址不对 | 改 `LLMCONSOLE_LLAMA_BASE_URL` |
| 所有路径都失败 | 推理服务只监听 unix socket | 改成 TCP 监听，或用反向代理 |
| `/props` 通但识别成 openai-compatible | 不是 llama.cpp 而是别的框架 | 正常，属于兜底识别 |
| 全是 404 | 装的是 Ollama 但探的是 8080 | Ollama 默认 **11434** |

### 识别成 "openai-compatible" 是什么意思？

表示**只认出了 OpenAI 兼容接口，没认出具体是哪个框架**。

控制台的判定顺序是"先专有信号、后通用兜底"。走到这一档说明
候选的专有端点（`/props`、`/api/version`、`/get_model_info`、`/version`）都没命中。

此时模型参数与槽位明细不可用，但 `/v1/models` 相关的信息仍会显示。

如果你用的是本项目已支持的框架却落到这一档，请开 Issue 并附上
`framework.probes` 的内容 —— 这通常意味着该框架某个版本改了端点。

### 怎么支持一个新的推理框架？

在 `app/services/framework.py` 的 `SPECS` 数据表里加一项，**不需要写 `if` 分支**：

```python
FrameworkSpec(
    id="myframework",
    name_zh="我的框架",
    name_en="My Framework",
    require_paths=("/my/version",),          # 必须可用的路径
    match=(("/my/version", "version"),),      # 判定信号：该 JSON 键存在即命中
    version_path="/my/version",
    version_keys=("version",),
    capabilities=frozenset({CAP_MODELS, CAP_HEALTH}),
    metrics_prefix="myfw:",
    note_zh="我的框架不提供 /slots，槽位明细不可用",
    note_en="My framework has no /slots; per-slot detail is unavailable",
)
```

然后按 `tests/test_framework.py` 的模式补一个假响应测试。

### 为什么 Ollama/vLLM/SGLang 没有「槽位」面板？

因为它们**不提供** `/slots` 这类槽位级接口。这不是缺陷，是框架能力差异。

控制台会明确显示「当前推理框架不提供槽位接口」，而不是显示空白表格或误报降级。

---

## 数据与显示

### 为什么「历史服务日志」选 30 天却只覆盖 12 天？

页面上的 `covered_days` 是**实际覆盖天数**，会小于你选的档位。
原因通常是：被监控的服务本身没有那么久的日志。

```bash
# 确认该单元最早的一条日志
journalctl -u <推理服务> --no-pager -o short-iso | head -1
```

如果该单元最近才创建，那 30 天档位自然只能拿到创建后的日志。
**控制台如实反映这一点，不会谎称覆盖了 30 天。**

### 磁盘容量显示得特别大？

控制台按**块设备**去重。systemd 的 `ProtectSystem` / `ReadWritePaths`
会把同一个分区绑定挂载到多个路径，按挂载点统计会重复计算。

如果你看到容量明显不对，欢迎开 Issue 并附上 `lsblk -o NAME,SIZE,MOUNTPOINT,TYPE` 的输出。

### 显卡没有风扇转速显示？

**这是刻意的。** 数据中心卡（如 Tesla 系列）通过 `nvidia-smi` 读风扇转速会返回 `[N/A]`。
控制台把 `[N/A]` 一律转为"未知"而**不转成 0** —— 否则会产生假的"风扇停转"告警。

### KV 余量显示「容量模式未知」？

说明控制台无法判定推理服务的 KV 池模式。判定优先级是：

**人工覆盖 → 单元文件的 `-kvu` 参数 → `-c` 算术关系 → 日志 → 未知**

判定不出来时**如实显示未知，不猜** —— 猜错会让 KV 余量完全失真。

想强制指定：

```ini
LLMCONSOLE_KV_MODE_OVERRIDE=unified    # 或 per_slot
```

### 告警一直挂着不消失？

阈值告警和事件告警**都会自动恢复**：

| 类型 | 恢复条件 |
| --- | --- |
| 阈值告警 | 指标回到阈值内 |
| 事件告警 | 超过 `event_alert_ttl_s`（默认 60 秒）未再发生 |

如果事件告警不消失，检查 `event_alert_ttl_s` 是否被设成了 `0`（`0` = 不自动恢复）。

### 基线的数值是多少才对？

**不要手填基线。** 保持 `mtp_accept_baseline` 和 `decode_baseline_tps` 为 `None`，
让控制台在你自己的机器上自动学习。

写死基线会导致换机器、换模型、换量化格式后告警持续误报。

重新学习：

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

---

## 安全性

### 控制台怎么没有登录？

**这是有意的设计取舍。** 本项目面向内网单机部署，引入认证会增加部署复杂度
（用户体系、会话、密码存储……），而收益有限。

请用**网络层**隔离：

- 只监听内网地址
- 用反向代理（Nginx/Caddy）加 Basic Auth 或 SSO
- **不要把 8081 暴露到公网**

详见 [安全策略](../SECURITY.md)。

### 服务管理按钮是灰的？

说明 sudo 白名单没有安装，或安装不正确。

```bash
# 检查白名单
sudo -n systemctl reset-failed <你的推理单元> && echo "白名单生效"

# 重新安装
SUDO_PW='...' LLM_INFER_UNIT=<你的推理单元> bash deploy/install_sudoers.sh
```

**不需要这个功能就不要装** —— 只读模式更安全。

### 单元文件里为什么放宽了 systemd 加固？

因为三项加固与功能直接冲突，单元文件中已逐条注明原因：

| 设置 | 冲突 |
| --- | --- |
| `NoNewPrivileges=no` | `yes` 会让 setuid 位失效，`sudo` 无法提权 |
| `PrivateDevices=no` | `yes` 会让 `/dev/nvidia*` 消失，`nvidia-smi` 报错 |
| `CapabilityBoundingSet` 非空 | 清空后 `sudo` 拿不到 `CAP_SETUID`/`CAP_SETGID` |
| `ProtectProc=default` | `invisible` 会让 psutil 看不到推理进程 |

**不需要服务管理功能时**，建议改回推荐值以获得更高安全性。

---

## 开发

### `selfcheck.sh` 里 format 检查失败，但代码看着没问题

在 Windows 上开发时，编辑器/Python 默认会写 **CRLF** 行尾。传到 Linux 后：

- shell 脚本直接报 `set: pipefail: invalid option name`
- 无扩展名的配置文件（如 sudoers）会**直接失效**
- `ruff format --check` 也会失败

```bash
python tools/fix_line_endings.py          # 归一为 LF
python tools/fix_line_endings.py --check  # 只检查
```

### 为什么 ruff 里开了 `ASYNC` 规则集？

它能**静态拦截** `async def` 里调用 `subprocess.run`、`time.sleep` 这类错误。
这类问题在运行时完全不可见，只表现为偶发卡顿，极难排查。
`ASYNC` 规则集让它在 CI 阶段就被拦住。

### 注释里写了示例代码，守卫误报了

**源码扫描类守卫必须先在匹配前剥离注释。** 参考 `tests/test_defect_ledger.py`：

```python
_strip_py(src)   # 剥离 Python 注释与文档字符串
_code(src)       # 只保留可执行代码
```

直接用 `src.find("if not fields:")` 会命中注释里的示例，产生错误结论。

### 怎么生成 Word 版文档？

项目里的 `.md` 文档可以用内置工具转成 `.docx`：

```bash
./venv/bin/pip install -e '.[docs]'
./venv/bin/python tools/md2docx.py 输入.md 输出.docx "页眉文字"
```

该工具会处理中文排版细节（如只在 ASCII token 内部插入换行断点，
避免给中文插入零宽空格破坏文本）。

### 前端为什么不用 React/Vue？

被监控的机器往往**没有 Node.js**。用框架就意味着需要构建步骤，
也就意味着发布物里要有构建产物或让用户装 Node。

原生 JS 让这个项目保持"`git clone` 就能跑"。

### 前端为什么一张图片都没有？

零图片资源是硬约束：

- 不需要额外文件就能部署
- 不需要处理图片缓存与路径
- 深色主题的图标全部用 CSS/Unicode 实现

守卫 `deploy/check_frontend.py` 会拦截 `<img>`、`background-image` 和外部 `url(...)`。

---

## 其它

### 这个项目和大厂的可观测平台（Prometheus + Grafana）什么关系？

**不是替代关系。** 本项目定位是**单机、轻量、零依赖**：

- Prometheus + Grafana 适合多机、长期存储、复杂查询，但需要部署一整套组件
- 本项目适合"一台机器、跑起来就想看一眼"，`git clone` + 一条命令即可

如果你的推理集群已经有多机监控体系，本项目可能并不必要。
但如果你是"一台机器、不想为了看个显存装一整套"，它就是为这个场景写的。

### 能不能只看推理服务，不采集主机信息？

目前没有细粒度的开关。但可以：

- 把算力卡从 `accel_vendor_allowlist` 里移除（会显示"未检测到"）
- 关闭不需要的面板需要改前端代码，欢迎提 PR 讨论

### 项目会继续维护吗？

见 [更新日志](../CHANGELOG.md) 与 Issue 区。欢迎提交 PR。
