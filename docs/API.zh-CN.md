# API 文档

[English](API.md) · **中文**

控制台提供 REST 与 WebSocket 两类接口。默认监听 `http://<host>:8081`。

所有 REST 接口都返回 JSON。**数据结构中的面向用户文案同时提供中英两份**
（形态为 `{"zh": "...", "en": "..."}` 或语言无关的代码字段），由前端按当前语言渲染。

## 约定

### 健康检查

| 端点 | 用途 | 说明 |
| --- | --- | --- |
| `GET /api/health/live` | 存活探针 | 进程在跑就返回 200，**不检查依赖** |
| `GET /api/health/ready` | 就绪探针 | 关键采集源可用才返回 200 |
| `GET /api/health` | 详细健康 | 含各采集源状态与降级原因 |

> 部署脚本用 `live` 判断进程存活，用 `ready` 判断是否该切流量。
> **不要用 `ready` 做存活探针** —— 推理服务重启期间 `ready` 会短暂失败，
> 用它做存活探针会误杀控制台。

### 就绪原因码

`/api/health/ready` 与 `/api/overview` 的 `health.reason_codes` 是**语言无关的代码**，
前端再本地化：

| 代码 | 含义 |
| --- | --- |
| `slots_unavailable` | 推理服务的 `/slots` 接口不可用 |
| `gpu_unavailable` | `nvidia-smi` 不可用 |
| `journal_not_running` | `journalctl` 跟随器未运行 |
| `service_down` | 推理服务未运行 |
| `stale:<collector>` | 指定采集器数据陈旧 |

---

## 总览

### `GET /api/overview`

页面首屏与 WebSocket 推送使用的是同一个聚合结构。

```jsonc
{
  "ts": 1790000000.0,
  "stale": false,
  "branding": {
    "product_name": "WKL-LLM运维平台v0.5",
    "product_name_spaced": "WKL-LLM运维平台 v0.5",
    "product_version": "v0.5",
    "developer": "WKL-LLM运维平台",
    "develop_date": "2026.10.01"
  },
  "model": { "name": "...", "full_name": "...", "path": "..." },
  "kpi": { "...": "吞吐、MTP 接受率等" },
  "kv": { "...": "KV 容量、余量、槽位列表" },
  "runtime": { "...": "运行参数与徽标" },
  "system": { "...": "CPU、内存、自身开销" },
  "self": { "...": "控制台自身资源占用" },
  "alerts": [ { "code": "...", "level": "...", "value": 0 } ],
  "gpus": [ { "...": "逐卡温度/功耗/显存/利用率" } ],
  "accelerator_badge": { "...": "算力卡厂家与带宽" },
  "baseline": { "mtp_accept_baseline": 0.0, "decode_baseline_tps": 0.0, "state": "ready" },
  "llama_uptime_s": 0.0,
  "hardware_ts": 0.0,

  // v0.5：推理框架识别结果
  "framework": {
    "id": "llama.cpp",
    "name": { "zh": "llama.cpp（llama-server）", "en": "llama.cpp (llama-server)" },
    "version": "b11146",
    "version_source": "http:/props",
    "build": "7fe450e19",
    "capabilities": ["health", "metrics", "models", "props", "slots"],
    "metrics_prefix": "llamacpp:",
    "note": { "zh": "...", "en": "..." },
    "confidence": "exact",
    "detected_at": 1790000000.0,
    "probes": { "/props": 200, "/version": 0, "/api/version": 0 }
  },

  "thresholds": { "poll_interval_s": 2.0, "...": "前端用于取阈值" },
  "health": {
    "ready": true,
    "reasons": ["..."],
    "reason_codes": ["slots_unavailable"],
    "ws": { "...": "WebSocket 连接统计" }
  }
}
```

#### `framework` 字段（v0.5 新增）

| 字段 | 说明 |
| --- | --- |
| `id` | `llama.cpp` / `ollama` / `vllm` / `sglang` / `openai-compatible` / `unknown` |
| `name` | 中英双语的框架显示名 |
| `version` | 自动探测到的版本号；探测不到时为空字符串（**不编造**） |
| `version_source` | 版本来源，形如 `http:/api/version`；未取到时为 `unknown` |
| `build` | 额外构建信息（如 llama.cpp 的 commit） |
| `capabilities` | 可用接口清单：`props` / `slots` / `metrics` / `models` / `health` / `version` / `tags` / `ps` |
| `metrics_prefix` | Prometheus 指标前缀（`llamacpp:` / `vllm:` / `sglang:`；无则空串） |
| `confidence` | `exact`（命中专有信号）/ `fallback`（仅 OpenAI 兼容）/ `unknown` |
| `probes` | 各探测路径的 HTTP 状态，用于诊断"为什么识别成 unknown" |

**前端应当依据 `capabilities` 决定显示哪些面板**，例如不含 `slots` 时不要渲染槽位表格，
而是显示"该框架不提供此接口"。

---

## 分项数据

| 端点 | 内容 |
| --- | --- |
| `GET /api/gpu` | 逐卡温度、功耗、显存、利用率 |
| `GET /api/slots` | 槽位列表与 KV 容量 |
| `GET /api/llm` | 模型与推理服务信息 |
| `GET /api/system` | 主机 CPU、内存、磁盘、自身开销 |
| `GET /api/config` | 运行参数与徽标（含 KV 量化、容量模式） |
| `GET /api/history` | 图表用的历史数据点 |
| `GET /api/logs` | 最近的推理服务日志行 |
| `GET /api/hardware` | 硬件与软件栈清点结果 |

`GET /api/hardware` 的结果带缓存（默认 `hardware_ttl_s = 600` 秒），
因为硬件清点会执行多条外部命令。

---

## 告警

### `GET /api/alert-catalog`

告警码目录（14 个），含中英双语的名称与分类。

```jsonc
{
  "levels": { "crit": {"zh": "严重", "en": "Critical"}, "...": {} },
  "alerts": [
    {
      "code": "CLIENT_CANCEL",
      "level": "info",
      "category": { "zh": "请求处理", "en": "Request handling" },
      "name": { "zh": "客户端取消生成", "en": "Client cancelled generation" }
    }
  ]
}
```

### `GET /api/alert-log`

查询参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `limit` | `500` | 返回条数 |
| `level` | — | 按级别过滤（`crit` / `warn` / `info`） |
| `q` | — | 关键词搜索 |
| `event` | — | 按事件过滤（`raised` / `resolved`） |

```jsonc
{
  "total": 16,
  "raised": 8,
  "resolved": 8,
  "entries": [
    {
      "seq": 16,
      "ts": 1790000000.0,
      "iso": "2026-10-02 23:16:24",
      "code": "CLIENT_CANCEL",
      "level": "info",
      "event": "resolved",
      "category": { "zh": "请求处理", "en": "Request handling" },
      "name": { "zh": "客户端取消生成", "en": "Client cancelled generation" },
      "message": "...",
      "value": null,
      "service": "llama-server.service",
      "duration_s": 12.3
    }
  ]
}
```

**`raised` / `resolved` 成对**：事件型告警超过 `event_alert_ttl_s` 未再发生会自动恢复，
因此日志里会出现成对的记录。这曾经是一个真实缺陷（只有 raised 没有 resolved）。

---

## 服务日志

### `GET /api/logs/history`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `days` | `30` | 档位，取值来自 `log_history_days_options`（1 / 7 / 30） |
| `limit` | `15000` | 返回行数；省略时用 `log_history_default_limit` |

```jsonc
{
  "requested_days": 30,
  "covered_days": 12.82,
  "returned": 10379,
  "elapsed_ms": 5300.0,
  "cached": false,
  "lines": [ { "ts_local": "2026-10-02 23:16:24", "text": "..." } ]
}
```

> `covered_days` 是**实际覆盖天数**，可能小于 `requested_days` ——
> 当被监控服务的历史日志不足 30 天时如实反映，不会谎称覆盖了 30 天。

结果带 TTL 缓存（`log_history_ttl_s`，默认 60 秒），缓存按 `(days, limit)` 组合索引并做 LRU 淘汰。

### `GET /api/logs/history/download`

同样的查询参数，返回 `text/plain` 附件下载（UTF-8 带 BOM，便于 Excel 直接打开）。

响应头包含 `Content-Disposition: attachment; filename=...`。

---

## 服务管理

### `GET /api/service/status`

推理服务的当前状态、运行时长与**授权情况**。

```jsonc
{
  "unit": "llama-server.service",
  "active": "active",
  "sub": "running",
  "uptime_s": 86400.0,
  "authorized": true,
  "actions": ["restart", "stop", "start"],
  "progress_code": "restarting"
}
```

`authorized` 表示 sudo 白名单是否已正确安装。为 `false` 时页面上的按钮不可用。

### `POST /api/service/{action}`

`action` ∈ `restart` / `stop` / `start`（由 `service_actions` 配置决定）。

需要 sudo 白名单已安装（见 [安装说明](INSTALL.md)）。

```jsonc
{ "ok": true, "action": "restart", "message": { "zh": "...", "en": "..." } }
```

> **该接口会真实重启你的推理服务**，正在处理的请求会中断。

---

## WebSocket

### `WS /ws/metrics`

推送聚合快照，形态与 `GET /api/overview` 一致。默认每 `poll_interval_s` 秒一帧。

告警变化会单独推送。

### `WS /ws/logs`

推理服务的实时日志流。

| 帧类型 | 说明 |
| --- | --- |
| 首帧 `backfill` | 连接建立时的历史回填（默认 40 行），**不代表新日志** |
| 后续帧 `log` | 实时新增的日志行 |

客户端应当**忽略首帧 `backfill`** 来做增量计数，否则会把历史日志误算成新日志。

连接释放时服务端会正确移除订阅。

---

## 静态资源

| 路径 | 内容 |
| --- | --- |
| `GET /` | 主控制台 |
| `GET /alerts.html` | 告警日志页 |
| `GET /logs.html` | 历史服务日志页 |
| `GET /app.js`、`/i18n.js`、`/style.css` | 前端资源 |

---

## 示例

```bash
# 当前框架与版本
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; f=json.load(sys.stdin)["framework"]; print(f["id"], f["version"], f["capabilities"])'

# 最近的严重告警
curl -s 'http://127.0.0.1:8081/api/alert-log?level=crit&limit=20'

# 最近 1 天日志的前 5 行
curl -s 'http://127.0.0.1:8081/api/logs/history?days=1&limit=5'

# 下载 7 天日志
curl -sO -J 'http://127.0.0.1:8081/api/logs/history/download?days=7'
```
