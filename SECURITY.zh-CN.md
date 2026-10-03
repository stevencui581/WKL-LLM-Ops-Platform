# 安全策略

[English](SECURITY.md) · **中文**

## 支持的版本

安全修复只针对最新发布版本。

| 版本 | 是否支持 |
| --- | --- |
| v0.6.x | ✅ |
| < v0.6 | ❌ |

## 报告漏洞

**请不要通过公开 Issue 报告安全漏洞。**

打开仓库的 [Security 标签页](https://github.com/stevencui581/WKL-LLM-Ops-Platform/security)，
点击 **Report a vulnerability**；或直接访问
[私密漏洞报告表单](https://github.com/stevencui581/WKL-LLM-Ops-Platform/security/advisories/new)。

GitHub 官方说明：
[私密报告安全漏洞](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)。

请在报告中包含：

- 受影响的版本
- 复现步骤（越具体越好）
- 影响范围与可能的利用方式
- 如果你有修复思路，也欢迎一并说明

我们会在 **7 天内**确认收到，并在修复发布后致谢（除非你希望匿名）。

## 部署安全须知

本项目设计为**在受信任的内网中运行**。请务必了解以下几点：

### 控制台自身没有认证

控制台**不提供登录**。任何能访问 `http://<host>:8081` 的人都能看到监控数据，
并且在启用服务管理功能后能**重启/停止你的推理服务**。

请务必：

- 只监听内网地址，或用反向代理加认证
- 不要把 8081 端口暴露到公网
- 不需要服务管理功能时，不要安装 sudoers 白名单（见下）

### 服务管理依赖最小化 sudo 白名单

`deploy/install_sudoers.sh` 会安装 `/etc/sudoers.d/llm-console`，
**只放行被监控推理单元的三个动作**（`restart` / `stop` / `start` / `reset-failed`），
不放行任意 `systemctl` 命令。

不需要这个能力时请不要安装：

```bash
SUDO_PW='...' bash deploy/install_sudoers.sh --remove
```

### 单元文件刻意放宽了三项 systemd 加固

`deploy/llm-console.service` 里 `NoNewPrivileges=no`、`PrivateDevices=no`、
`CapabilityBoundingSet` 非空，且文件内注明了原因：

| 设置 | 为什么放宽 |
| --- | --- |
| `NoNewPrivileges=no` | 该设置会让 setuid 位失效，`sudo` 无法提权，服务管理功能永远判定为「未授权」 |
| `PrivateDevices=no` | 该设置会让 `/dev/nvidia*` 消失，`nvidia-smi` 直接报错 |
| `CapabilityBoundingSet` 非空 | 清空后 `sudo` 拿不到 `CAP_SETUID`/`CAP_SETGID`，白名单配好也一定失败 |
| `ProtectProc=default` | `ProtectProc=invisible` 会让 psutil 看不到推理进程 |

**如果你不需要服务管理功能**，建议改回 systemd 的推荐值（`NoNewPrivileges=yes`
并清空 `CapabilityBoundingSet`），安全性更高。请在 PR 或部署说明中注明你的选择。

### 凭据不进仓库

`deploy/host.env` 已被 `.gitignore` 忽略。请**不要**把你的服务器地址、用户名或密码
提交到仓库、Issue 或截图里。示例配置见 `deploy/host.env.example`。

## 已知的设计取舍

| 取舍 | 说明 |
| --- | --- |
| 无认证 | 面向内网单体部署，引入认证会增加部署复杂度；请用网络层隔离 |
| 服务管理需要 sudo | 通过最小化白名单把风险限制在单个 unit 的四个动作 |
| 采集器读取 journald | 需要 `systemd-journal` 或 `adm` 组成员身份 |

如果你认为某个取舍在特定场景下不可接受，欢迎开 Issue 讨论。
