# Architecture

[中文](ARCHITECTURE.zh-CN.md) · **English** · [Project home](../README.md) · [Installation](INSTALL.md)

## Design goals

Provide a readable runtime view of a local LLM inference service on a **single machine**. Three constraints shape the overall architecture:

1. **Zero-dependency frontend** — monitored machines usually have no Node.js, so the frontend must be plain JavaScript with no build step
2. **Single process** — collection state is shared inside the process, avoiding heavy components such as Redis or a message queue
3. **Portable** — switching framework, hardware or machine needs no code change

## Data flow

```
                     ┌─────────────────────────────────────────────┐
                     │  Inference service (same host)              │
                     │  llama.cpp / Ollama / vLLM / SGLang         │
                     └───────────────┬─────────────────────────────┘
                                     │
        ┌────────────────────────────┼──────────────────────────────┐
        │                            │                              │
   HTTP API                   Prometheus text               systemd / journald
   /props /slots              /metrics                      unit state, logs, events
   /v1/models /health                                       (journalctl follow)
        │                            │                              │
        ▼                            ▼                              ▼
 ┌──────────────┐          ┌──────────────┐              ┌────────────────┐
 │ Framework    │          │ Metrics      │              │ Log            │
 │ detection    │          │ collector    │              │ collector      │
 │ framework.py │          │ prometheus.py│              │ journal.py     │
 └──────┬───────┘          └──────┬───────┘              └───────┬────────┘
        │ capability list         │                              │
        │ (decides which          │                              │
        │  collectors are on)     │                              │
        └──────────────┬──────────┴──────────────────────────────┘
                       ▼
              ┌────────────────────┐        ┌──────────────────┐
              │ Aggregator         │◄───────│ Hardware         │
              │ aggregator.py      │        │ inventory        │
              │ concurrent collect │        │ hardware.py      │
              │ + capability trim  │        │ (nvidia-smi /    │
              └─────────┬──────────┘        │  lscpu / lsblk…) │
                        │                   └──────────────────┘
                        ▼
              ┌────────────────────┐
              │ Alert engine       │  ← automatic baseline baseline.py
              │ alerts.py          │
              │ threshold + event  │
              │ alerts, with       │
              │ auto-recovery      │
              └─────────┬──────────┘
                        │
              ┌─────────▼──────────┐
              │ FastAPI routes     │
              │ REST + WebSocket   │
              └─────────┬──────────┘
                        ▼
              ┌────────────────────────┐
              │ Plain JS frontend      │  Language is chosen in the frontend;
              │ three static pages     │  the backend sends structured fields only
              └────────────────────────┘
```

## Core modules

### `app/services/framework.py` — inference framework detection

**The problem it solves**: the console was originally designed around llama.cpp's proprietary
endpoints (`/props`, `/slots`, `/metrics llamacpp:*`). With Ollama/vLLM/SGLang those endpoints do
not exist, so the UI was largely blank plus a storm of stale alerts —
it looked like the console was broken, when in fact only the framework was different.

**The approach**: at startup, candidate endpoints are probed in priority order (proprietary signals
first, generic fallback last), producing
`FrameworkInfo{id, name_zh, name_en, version, capabilities, metrics_prefix, metrics_map}`.

`metrics_map` maps **language-neutral metric concepts** (e.g. `tokens_generated_total`,
`requests_waiting`) to each framework's actual Prometheus series names. The collector only knows
concepts, so adding a framework never requires touching `app/collectors/prometheus.py`.

| Framework | Detection signal | Version source |
| --- | --- | --- |
| llama.cpp | `/props` contains `build_info` / `default_generation_settings` / `total_slots` | `/props` → `build_info` |
| Ollama | `/api/version` contains `version` | `/api/version` |
| SGLang | `/get_model_info` contains `model_path` / `model_name` | `/get_server_info` |
| vLLM | both `/version` and `/v1/models` are available | `/version` (plain text) |
| OpenAI-compatible | only `/v1/models` is available | — |

Order matters: llama.cpp, vLLM and SGLang **all** expose `/v1/models`,
so proprietary signals must come before the generic fallback, or they would be misidentified as
"OpenAI-compatible".

The detection result is handed to the collectors through `aggregator.set_framework()`, which
implements **capability trimming**: endpoints the framework does not have are no longer probed and
no longer counted as failures. When detection fails it is retried every `framework_redetect_s`,
which covers the "console started first, inference service started later" ordering.

**How to extend**: add one entry to the `SPECS` data table; no `if framework == ...` is needed.
The guard test `test_no_hardcoded_framework_in_collectors` blocks hard-coded framework names.

### `app/services/aggregator.py` — collection aggregation

- **Concurrent collection**: several data sources are fetched in parallel, so the overall latency is
  that of the slowest source rather than the sum
  (hardware inventory used to exceed the 200 ms budget when serial; concurrent collection brought it
  down to about 125 ms)
- **Capability trimming**: each collector is switched on or off according to the framework's capabilities
- **Events to alerts**: changes in the event counters found in the logs are turned into alerts

### `app/collectors/` — the data sources

| Collector | Data source | Notes |
| --- | --- | --- |
| `slots.py` | `/slots` | per-slot context, prompt cache; not enabled for frameworks without a slots endpoint |
| `props.py` | `/props`, `/v1/models` | model parameters and KV configuration; the two capabilities can be toggled separately |
| `prometheus.py` | `/metrics` | Prometheus text parsing; a different prefix per framework |
| `gpu.py` | `nvidia-smi` | temperature/power/VRAM/utilisation; every `[N/A]` becomes `None`, never 0 |
| `hardware.py` | `lscpu`/`lsblk`/`nvidia-smi`/`nvcc` etc. | everything probed at runtime; anything missing shows "not installed" |
| `journal.py` | `journalctl -f` | follows the inference service log and parses events |
| `history.py` | `journalctl --since` | on-demand 1/7/30-day queries + LRU cache |

### `app/services/alerts.py` — alert engine

Two kinds of alert:

- **Threshold alerts**: compared against a baseline (KV utilisation, temperature, power, throughput deviation)
- **Event alerts**: a specific event appears in the log (process exit, context truncation, client cancellation)

**Key design: both kinds of alert must be able to recover automatically.** Event alerts are cleared by
the `event_alert_ttl_s` timeout; otherwise a single client cancellation would leave an alert hanging in
the UI forever, and the alert log would hold `raised` entries with no `resolved` counterpart.

**Baselines come from automatic learning** (`baseline.py`), not from hard-coded numbers:
while the service runs healthily the console learns the MTP acceptance rate and the decode throughput,
freezes them, and uses them as the reference for later alerts.

### `app/services/alert_log.py` / `alert_catalog.py` — alert log and catalog

- `alert_catalog.py`: Chinese and English names, levels and categories for 14 alert codes (table-driven)
- `alert_log.py`: ring buffer (2000 entries in memory) + on-disk file (10000 entries);
  `sync()` uses **differential semantics** to decide `raised` / `resolved`

### Frontend (`static/`)

**Three layers of internationalisation**:

1. HTML marks copy with `data-i18n` attributes
2. JS fetches copy through `t(key, params)`
3. **The backend sends structured fields and language-neutral codes**, and the frontend renders them in the current language

Language resolution order: `localStorage` (manual choice, permanent) → `navigator.languages` → fallback `zh`.

**Why the backend does not return Chinese sentences directly**: the frontend could not switch languages
then. The backend either returns a code (such as `progress_code`) or returns both languages at once
(such as `name: {zh, en}`).

## Design principles

### 1. Every hardware fact is probed at runtime

No concrete model, driver version, path or model file name may appear in production code. The rules:

| Case | Display |
| --- | --- |
| Probe succeeds | the real value |
| Probe fails | "unknown" |
| Component not installed | "not installed" |

**Never substitute a default value**, and never guess either. Guards:
`tests/test_no_hardcoded_deployment.py`, `tests/test_open_source_compliance.py`.

### 2. Trim capabilities per framework instead of raising errors

The framework does not provide an endpoint → state plainly that "this framework does not provide this
endpoint", and record it in the log as a "capability difference" rather than a "fault". That is what
makes the "degraded" marker in the UI meaningful.

### 3. Separate data from presentation

The backend sends language-neutral structured fields; the frontend decides which language to display
them in. The `en` dictionary must not contain CJK characters (guard: `tests/test_i18n.py`).

### 4. Gates must be reliable

Source-scanning guards **must strip comments before matching**. Example code inside a comment makes the
guard misjudge — it can miss a violation (treating a comment as code) or raise a false one (treating an
example as a violation).

This is a real lesson: the v0.4.4 BOM defect was dangerous precisely because the BOM broke the
"first line is the docstring" check, which made every source-scanning guard meaningless. Reference
implementation: `_strip_py()` / `_code()` in `tests/test_defect_ledger.py`.

### 5. A permanently red gate is no gate at all

A one-off script is either deleted or **explicitly exempted in `pyproject.toml` with the reason
stated**. A gate that stays red for a long time teaches everyone to ignore it.

## Deployment model

```
/opt/WKL-LLM-Ops-Platform/                  ← deployment root (configurable)
├── venv/                          virtual environment
├── releases/
│   ├── 20261003-001313/           one complete directory per release
│   └── 20261003-002616/           ← new version
├── current -> releases/20261003-002616    atomic symlink
├── state/                         runtime state (baseline, alert log, log cursor)
└── logs/
```

Release procedure (`deploy/deploy.sh`):

1. Package the current code into `releases/<timestamp>`
2. Smoke test
3. Atomically switch the `current` symlink (`ln -sfnT` + `mv -T`, to avoid a window during the switch)
4. Restart the service and run a health check
5. **Roll back automatically to the previous version if the health check fails**

Rolling back is just `bash deploy/rollback.sh` (takes seconds).

## Why a single worker

| Component | Where its state lives |
| --- | --- |
| journalctl follower | in-process child process + cursor file |
| WebSocket broadcast | in-process connection set |
| Hardware inventory cache | in-process memory |
| Baseline learning | in-process + on disk |

Multiple workers would each pull their own journalctl stream and maintain their own connection set,
which both wastes resources and makes the data inconsistent. The collection volume itself is small
(about 88 MB of memory), so a single worker is plenty.

## Related documents

- [Installation](INSTALL.md)
- [Configuration](CONFIGURATION.md)
- [API](API.md)
- [Troubleshooting](TROUBLESHOOTING.md)
