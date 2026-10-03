# API

[中文](API.zh-CN.md) · **English** · [Project home](../README.md) · [Installation](INSTALL.md)

The console exposes two kinds of interface, REST and WebSocket. It listens on
`http://<host>:8081` by default.

All REST endpoints return JSON. **User-facing copy inside the data structures is provided in both
Chinese and English** (either as `{"zh": "...", "en": "..."}` or as a language-neutral code field) and
is rendered by the frontend in the current language.

> In the examples below the Chinese half of a bilingual pair is abbreviated to `"..."`; in a real
> response it carries the Chinese string.

## Conventions

### Health checks

| Endpoint | Purpose | Notes |
| --- | --- | --- |
| `GET /api/health/live` | liveness probe | returns 200 as long as the process runs, **it does not check dependencies** |
| `GET /api/health/ready` | readiness probe | returns 200 only when the critical collection sources are available |
| `GET /api/health` | detailed health | includes each collection source's state and the reason for degradation |

> Deployment scripts use `live` to tell whether the process is alive and `ready` to tell whether traffic
> should be routed to it.
> **Do not use `ready` as a liveness probe** — `ready` fails briefly while the inference service
> restarts, and using it as a liveness probe would kill the console.

### Readiness reason codes

`health.reason_codes` in `/api/health/ready` and `/api/overview` consists of **language-neutral codes**
that the frontend localises:

| Code | Meaning |
| --- | --- |
| `slots_unavailable` | the inference service's `/slots` endpoint is unavailable |
| `gpu_unavailable` | `nvidia-smi` is unavailable |
| `journal_not_running` | the `journalctl` follower is not running |
| `service_down` | the inference service is not running |
| `stale:<collector>` | the data of the given collector is stale |

---

## Overview

### `GET /api/overview`

The first page load and the WebSocket pushes use the same aggregate structure.

```jsonc
{
  "ts": 1790000000.0,
  "stale": false,
  "branding": {
    "product_name": "WKL-LLM Ops Platformv0.5",
    "product_name_spaced": "WKL-LLM Ops Platform v0.5",
    "product_version": "v0.5",
    "developer": "WKL-LLM Ops Platform",
    "develop_date": "2026.10.01"
  },
  "model": { "name": "...", "full_name": "...", "path": "..." },
  "kpi": { "...": "throughput, MTP acceptance rate, ..." },
  "kv": { "...": "KV capacity, headroom, slot list" },
  "runtime": { "...": "runtime arguments and badges" },
  "system": { "...": "CPU, memory, self overhead" },
  "self": { "...": "the console's own resource usage" },
  "alerts": [ { "code": "...", "level": "...", "value": 0 } ],
  "gpus": [ { "...": "per-card temperature/power/VRAM/utilisation" } ],
  "accelerator_badge": { "...": "accelerator vendor and bandwidth" },
  "baseline": { "mtp_accept_baseline": 0.0, "decode_baseline_tps": 0.0, "state": "ready" },
  "llama_uptime_s": 0.0,
  "hardware_ts": 0.0,

  // v0.5: inference framework detection result
  "framework": {
    "id": "llama.cpp",
    "name": { "zh": "...", "en": "llama.cpp (llama-server)" },
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

  "thresholds": { "poll_interval_s": 2.0, "...": "thresholds the frontend reads" },
  "health": {
    "ready": true,
    "reasons": ["..."],
    "reason_codes": ["slots_unavailable"],
    "ws": { "...": "WebSocket connection statistics" }
  }
}
```

#### The `framework` field (new in v0.5)

| Field | Notes |
| --- | --- |
| `id` | `llama.cpp` / `ollama` / `vllm` / `sglang` / `openai-compatible` / `unknown` |
| `name` | framework display name in both Chinese and English |
| `version` | automatically detected version; an empty string when it cannot be detected (**never invented**) |
| `version_source` | where the version came from, of the form `http:/api/version`; `unknown` when unavailable |
| `build` | extra build information (such as the llama.cpp commit) |
| `capabilities` | available endpoints: `props` / `slots` / `metrics` / `models` / `health` / `version` / `tags` / `ps` |
| `metrics_prefix` | Prometheus metric prefix (`llamacpp:` / `vllm:` / `sglang:`; empty when there is none) |
| `confidence` | `exact` (a proprietary signal matched) / `fallback` (OpenAI-compatible only) / `unknown` |
| `probes` | HTTP status of each probe path, used to diagnose "why was it detected as unknown" |

**The frontend should decide which panels to render from `capabilities`**; for example, when `slots` is
absent it must not render the slot table but show "this framework does not provide this endpoint"
instead.

---

## Per-section data

| Endpoint | Content |
| --- | --- |
| `GET /api/gpu` | per-card temperature, power, VRAM, utilisation |
| `GET /api/slots` | slot list and KV capacity |
| `GET /api/llm` | model and inference service information |
| `GET /api/system` | host CPU, memory, disk, self overhead |
| `GET /api/config` | runtime arguments and badges (including KV quantisation and capacity mode) |
| `GET /api/history` | historical data points for the charts |
| `GET /api/logs` | recent inference service log lines |
| `GET /api/hardware` | hardware and software stack inventory |

`GET /api/hardware` results are cached (default `hardware_ttl_s = 600` seconds),
because hardware inventory runs several external commands.

---

## Alerts

### `GET /api/alert-catalog`

The alert code catalog (14 entries), with names and categories in Chinese and English.

```jsonc
{
  "levels": { "crit": {"zh": "...", "en": "Critical"}, "...": {} },
  "alerts": [
    {
      "code": "CLIENT_CANCEL",
      "level": "info",
      "category": { "zh": "...", "en": "Request handling" },
      "name": { "zh": "...", "en": "Client cancelled generation" }
    }
  ]
}
```

### `GET /api/alert-log`

Query parameters:

| Parameter | Default | Notes |
| --- | --- | --- |
| `limit` | `500` | number of entries returned |
| `level` | — | filter by level (`crit` / `warn` / `info`) |
| `q` | — | keyword search |
| `event` | — | filter by event (`raised` / `resolved`) |

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
      "category": { "zh": "...", "en": "Request handling" },
      "name": { "zh": "...", "en": "Client cancelled generation" },
      "message": "...",
      "value": null,
      "service": "llama-server.service",
      "duration_s": 12.3
    }
  ]
}
```

**`raised` / `resolved` come in pairs**: an event alert recovers automatically once
`event_alert_ttl_s` passes without it happening again, so paired entries appear in the log. This used to
be a real defect (only `raised` and no `resolved`).

---

## Service logs

### `GET /api/logs/history`

| Parameter | Default | Notes |
| --- | --- | --- |
| `days` | `30` | range, its values come from `log_history_days_options` (1 / 7 / 30) |
| `limit` | `15000` | number of lines returned; `log_history_default_limit` is used when omitted |

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

> `covered_days` is the number of days **actually covered**, and may be smaller than `requested_days` —
> when the monitored service's service log history is shorter than 30 days, that is reported as it is,
> rather than claiming 30 days of coverage.

Results are cached with a TTL (`log_history_ttl_s`, 60 seconds by default); the cache is indexed by the
`(days, limit)` combination and evicted with LRU.

### `GET /api/logs/history/download`

The same query parameters, returning a `text/plain` attachment download (UTF-8 with BOM, so Excel can
open it directly).

The response carries `Content-Disposition: attachment; filename=...`.

---

## Service control

### `GET /api/service/status`

The inference service's current state, uptime and **authorisation status**.

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

`authorized` tells whether the sudo allowlist is installed correctly. When it is `false`, the buttons on
the page are unavailable.

### `POST /api/service/{action}`

`action` ∈ `restart` / `stop` / `start` (determined by the `service_actions` configuration).

Requires the sudo allowlist to be installed (see [Installation](INSTALL.md)).

```jsonc
{ "ok": true, "action": "restart", "message": { "zh": "...", "en": "..." } }
```

> **This endpoint really does restart your inference service**; requests being processed are interrupted.

---

## WebSocket

### `WS /ws/metrics`

Pushes aggregate snapshots with the same shape as `GET /api/overview`. One frame every
`poll_interval_s` seconds by default.

Alert changes are pushed separately.

### `WS /ws/logs`

The live log stream of the inference service.

| Frame type | Notes |
| --- | --- |
| first frame `backfill` | history backfilled when the connection is established (40 lines by default), **not new log lines** |
| later frames `log` | newly arriving log lines |

Clients should **ignore the first `backfill` frame** when counting increments, or they will count
historical lines as new ones.

The server removes the subscription correctly when the connection is released.

---

## Static assets

| Path | Content |
| --- | --- |
| `GET /` | main console |
| `GET /alerts.html` | alert log page |
| `GET /logs.html` | service log history page |
| `GET /app.js`, `/i18n.js`, `/style.css` | frontend assets |

---

## Examples

```bash
# Current framework and version
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; f=json.load(sys.stdin)["framework"]; print(f["id"], f["version"], f["capabilities"])'

# Most recent critical alerts
curl -s 'http://127.0.0.1:8081/api/alert-log?level=crit&limit=20'

# First 5 lines of the last day's logs
curl -s 'http://127.0.0.1:8081/api/logs/history?days=1&limit=5'

# Download 7 days of logs
curl -sO -J 'http://127.0.0.1:8081/api/logs/history/download?days=7'
```
