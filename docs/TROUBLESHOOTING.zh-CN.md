# 故障排查

[English](TROUBLESHOOTING.md) · **中文**

本文档按**现象**组织。每条给出：可能原因 → 诊断命令 → 处理方式。

## 快速诊断

```bash
# 1. 控制台服务本身
systemctl status llm-console.service
journalctl -u llm-console.service -n 50 --no-pager

# 2. 三个健康端点
curl -s -o /dev/null -w 'live=%{http_code}\n'     http://127.0.0.1:8081/api/health/live
curl -s -o /dev/null -w 'ready=%{http_code}\n'    http://127.0.0.1:8081/api/health/ready
curl -s -o /dev/null -w 'overview=%{http_code}\n' http://127.0.0.1:8081/api/overview

# 3. 就绪原因（哪一项导致未就绪）
curl -s http://127.0.0.1:8081/api/health | python3 -m json.tool

# 4. 框架识别结果与探测详情
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["framework"], ensure_ascii=False, indent=2))'
```

---

## 控制台起不来

### `systemctl status` 显示 `failed` 或反复重启

```bash
journalctl -u llm-console.service -n 100 --no-pager
```

| 日志特征 | 原因 | 处理 |
| --- | --- | --- |
| `Address already in use` | 8081 被占用 | `ss -lntp \| grep 8081` 找到占用者，或改端口 |
| `ModuleNotFoundError` | venv 未安装依赖或路径不对 | 检查单元文件里 `ExecStart` 的 Python 路径，重新 `pip install -e .` |
| `pydantic_core.ValidationError` | 配置项拼写错误 | `extra="forbid"` 会让未知变量直接报错，按报错信息修正 |
| `Permission denied` 访问 state/ | 目录属主不对 | `chown -R <运行用户> state logs` |
| `reception only permitted for main PID` | 单元文件缺 `NotifyAccess=all` | 用仓库自带的单元文件模板 |

### `systemctl status` 显示 `masked`

**这是踩过的坑。** 单元文件被写成 0 字节时，systemd 会视为 masked。

成因：把渲染结果管道给 `sudo -S tee` —— `sudo -S` 从 stdin 读密码，
管道内容被密码提示吃掉，结果写出空文件。

```bash
# 确认文件大小
ls -la /etc/systemd/system/llm-console.service

# 重新安装（仓库里的 install_service.sh 已修复该问题：先写临时文件再 install）
LLM_INFER_UNIT=<你的推理单元> SUDO_PW='...' bash deploy/install_service.sh
```

### 服务起来了但页面打不开

```bash
# 本机能不能通
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/

# 监听地址对不对（0.0.0.0 vs 127.0.0.1）
ss -lntp | grep 8081

# 防火墙
sudo ufw status        # 或 firewall-cmd --list-all
```

如果 `0.0.0.0` 监听正常但外部访问不通，是防火墙或安全组问题。

---

## 页面数据为空或显示异常

### 整个页面全是「—」

说明 `/api/overview` 拿不到数据。按顺序检查：

```bash
# 推理服务在跑吗
systemctl status <你的推理单元>

# HTTP 接口通吗（注意端口：llama.cpp 8080 / Ollama 11434 / vLLM 8000 / SGLang 30000）
curl -s http://127.0.0.1:8080/health

# 控制台配的地址对不对
systemctl show llm-console.service -p Environment
```

### 顶部「框架」显示"未识别"

见 [FAQ](FAQ.md)。关键诊断信息是 `framework.probes` ——
它列出每个候选端点的 HTTP 状态：

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["framework"]["probes"])'
```

`{"/props": 200, "/version": 0, "/api/version": 0}` 表示只有 `/props` 通了（llama.cpp）。

### 硬件面板说「未检测到」但明明有显卡

```bash
# 控制台用的命令能不能跑（注意：要用运行控制台的那个用户）
sudo -u <运行用户> nvidia-smi --query-gpu=index,name --format=csv,noheader

# 显卡的 PCI ID 在允许列表里吗
lspci -nn | grep -iE 'vga|3d|display'
```

- NVIDIA 应为 `10de`，AMD 应为 `1002`。其它厂家需要加进 `accel_vendor_allowlist`。
- QEMU 虚拟显卡（`1234:1111`）被默认排除，这是有意的。

### 日志面板是空的

```bash
# 单元名对不对
systemctl list-units --type=service | grep -iE 'llama|ollama|vllm|sglang'

# 该单元有日志吗
journalctl -u <你的推理单元> -n 5 --no-pager

# 当前用户能读 journald 吗
id    # 需要 systemd-journal 或 adm 组
```

控制台以部署时的当前用户运行。如果该用户不在 `systemd-journal` / `adm` 组里，会读不到日志：

```bash
sudo usermod -aG systemd-journal <运行用户>
sudo systemctl restart llm-console.service
```

### 日志面板显示"服务运行正常"但推理服务明显没在跑

```bash
systemctl is-active <你的推理单元>
journalctl -u llm-console.service | grep -i 'unit\|service'
```

检查 `LLMCONSOLE_LLAMA_UNIT` 是否指向了真实的单元名。

---

## 性能问题

### 控制台自己的 CPU 占用偏高

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"])'
```

预算：CPU < 2%，内存 < 200 MB。

如果超出：

1. **确认只有一个 worker**（`ps aux | grep uvicorn`）。多 worker 会让每个 worker 各自拉 journalctl。
2. 提高 `poll_interval_s`（默认 2 秒）。
3. 提高 `hardware_ttl_s`（默认 600 秒）。
4. 检查是否有慢命令：`journalctl -u llm-console.service | grep -i slow`。

### 内存持续增长

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"]["rss_mb"])'
```

本项目历史上出现过**历史日志缓存无界增长**（46 MB → 88 MB），
已通过 LRU 淘汰修复（上限 4 条）。

如果你看到持续增长，请记录下面信息并开 Issue：

```bash
# 观察 10 分钟，每分钟记录一次
for i in $(seq 1 10); do
  curl -s http://127.0.0.1:8081/api/overview \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"]["rss_mb"])'
  sleep 60
done
```

### 页面卡顿或 WebSocket 频繁断开

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["health"]["ws"])'
```

WebSocket 有背压保护：每个连接的发送队列上限 `ws_queue_max`（默认 100），
发送超时 `ws_send_timeout_s`（默认 5 秒）。**慢客户端会被主动断开**，这是设计行为。

如果正常客户端也频繁断开，检查网络抖动（`ws_ping_interval_s` 默认 30 秒）。

---

## 告警相关

### 告警一直不消失

| 类型 | 恢复条件 |
| --- | --- |
| 阈值告警 | 指标回到阈值内 |
| 事件告警 | 超过 `event_alert_ttl_s`（默认 60 秒）未再发生 |

```bash
# 确认 TTL 配置
systemctl show llm-console.service -p Environment | tr ' ' '\n' | grep -i TTL
```

`event_alert_ttl_s=0` 表示**不自动恢复**（不建议）。

### 告警日志只有 raised 没有 resolved

这曾经是一个真实缺陷（事件告警的自动恢复没生效）。
如果现在仍然出现：

```bash
curl -s 'http://127.0.0.1:8081/api/alert-log?limit=20' | python3 -m json.tool | head -60
```

请开 Issue，附上 `event_alert_ttl_s` 的配置值与上述输出。

### 告警误报（例如吞吐告警频繁触发）

最可能的原因是**基线不合适**。基线可能是在异常状态下学到的（比如学的时候服务正在被压测）。

```bash
# 看当前基线
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["baseline"])'
```

重新学习（在服务**正常运行**时做）：

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

或者放宽阈值：

```ini
LLMCONSOLE_MTP_DROP_RATIO=0.70
LLMCONSOLE_DECODE_DROP_RATIO=0.40
```

---

## 服务管理不可用

### 按钮是灰的

```bash
# 白名单装了吗
sudo -n systemctl reset-failed <你的推理单元> && echo "生效" || echo "未生效"

# 控制台自己的判定
curl -s http://127.0.0.1:8081/api/service/status | python3 -m json.tool
```

重装白名单：

```bash
SUDO_PW='...' LLM_INFER_UNIT=<你的推理单元> bash deploy/install_sudoers.sh
```

### 白名单装了但提示未授权

按顺序检查：

```bash
# 1. sudoers 文件语法
sudo visudo -c -f /etc/sudoers.d/llm-console

# 2. 单元名写对了吗（必须完全匹配）
sudo cat /etc/sudoers.d/llm-console

# 3. 单元文件里 NoNewPrivileges 是 no 吗
systemctl show llm-console.service -p NoNewPrivileges

# 4. 能力界限集是空的吗（空 = sudo 拿不到 CAP_SETUID）
systemctl show llm-console.service -p CapabilityBoundingSet
```

第 4 项如果显示 `CapabilityBoundingSet=`（空），必须改回非空 —— 见 [安全策略](../SECURITY.md)。

> 另注：`deploy/sudoers.llm-console` 必须是 **LF** 行尾。
> CRLF 会让 sudoers 解析失败，且 `visudo -c` 的报错不一定直观。
> CI 与 `python tools/fix_line_endings.py --check` 会拦住这个问题。

---

## 部署与升级

### 升级后页面没变化

```bash
# 看当前指向哪个版本
ls -la current
systemctl show llm-console.service -p WorkingDirectory

# 浏览器缓存：强制刷新（Ctrl+Shift+R）
# 或直接看接口
curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; print(json.load(sys.stdin)["branding"]["product_version"])'
```

### 升级后服务不健康

`deploy/deploy.sh` 有健康门禁，失败会自动回滚。手动回滚：

```bash
bash deploy/rollback.sh
```

回滚是秒级的（只是切换软链接 + 重启服务）。

### 本地改了代码，服务器上的修复却"消失"了

**这是曾经的真实缺陷。** 成因：回传脚本的目录表缺少某些目录
（如 `probes`、`tools`），服务器上的修复无法回传本地，
下次上传又把未修复版本覆盖回去 —— 表现为"改了没效果"。

现在的流程（`deploy/preflight.py`）已修复该问题：

```bash
python3 deploy/preflight.py    # 上传 → 远端格式化+门禁 → 回传
```

**不要**只上传不同步，否则本地与远端会分叉。

---

## 采集与数据准确性

### 磁盘容量明显偏大

按块设备去重。若仍有问题，请附 `lsblk -o NAME,SIZE,MOUNTPOINT,TYPE` 输出开 Issue。

### 显存/利用率波动剧烈

可能是采集间隔太长（默认 2 秒）导致采样点少。可以降低 `poll_interval_s`，
但要注意自身开销预算。

### `[N/A]` 被显示成了 0

**不应该发生。** 本项目的约定是 `[N/A]` 一律转"未知"而**不转成 0**
（转 0 会产生假的低功耗/零温度告警）。

如果确实看到了 0，请开 Issue 并附上原始采集值。

---

## 收集诊断信息

开 Issue 前请运行下面这条，它会把关键信息打包输出（**请先检查并删除敏感信息**）：

```bash
{
  echo "=== 版本 ==="
  curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["branding"])'
  echo "=== 框架 ==="
  curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["framework"], ensure_ascii=False))'
  echo "=== 健康 ==="
  curl -s http://127.0.0.1:8081/api/health
  echo
  echo "=== 服务状态 ==="
  systemctl status llm-console.service --no-pager | head -20
  echo "=== 配置 ==="
  systemctl show llm-console.service -p Environment | tr ' ' '\n' | grep LLMCONSOLE
  echo "=== 系统 ==="
  uname -a
  python3 -V
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo "无 nvidia-smi"
  echo "=== 日志（尾部 50 行）==="
  journalctl -u llm-console.service -n 50 --no-pager
} > diag.txt 2>&1

echo "诊断信息已写入 diag.txt，请检查后再上传"
```
