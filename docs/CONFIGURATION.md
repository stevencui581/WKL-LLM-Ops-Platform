# Configuration

[中文](CONFIGURATION.zh-CN.md) · **English** · [Project home](../README.md) · [Installation](INSTALL.md)

Every setting is defined in the `Settings` class in **`app/config.py`** and loaded through
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

## Configuration sources and precedence

| Precedence | Source | Notes |
| --- | --- | --- |
| 1 (highest) | **Environment variables** | prefix `LLMCONSOLE_`, e.g. `LLMCONSOLE_LLAMA_UNIT` |
| 2 | **`.env` file** | project root, already ignored by `.gitignore` |
| 3 (lowest) | defaults in `app/config.py` | generic defaults that contain no deployment-specific facts |

Variable name = `LLMCONSOLE_` + the field name in upper case. Nested fields use a double underscore
(`env_nested_delimiter="__"`).

```bash
# Environment variable form
export LLMCONSOLE_LLAMA_UNIT=llama-server.service
export LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080
```

```ini
# .env form (recommended)
LLMCONSOLE_LLAMA_UNIT=llama-server.service
LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080
LLMCONSOLE_LOG_LEVEL=INFO
```

> A variable that is not declared in `Settings` **fails immediately** (`extra="forbid"`) —
> this is deliberate: it stops a misspelled name from silently falling back to the default.

---

## Monitored target

**This is the group you are most likely to change at deployment time.**

| Field | Environment variable | Default | Notes |
| --- | --- | --- | --- |
| `llama_base_url` | `LLMCONSOLE_LLAMA_BASE_URL` | `http://127.0.0.1:8080` | inference service HTTP address |
| `llama_unit` | `LLMCONSOLE_LLAMA_UNIT` | `llm-infer.service` | systemd unit under monitoring |
| `console_unit` | `LLMCONSOLE_CONSOLE_UNIT` | `llm-console.service` | the console's own unit (used for self-monitoring) |
| `nvidia_smi` | `LLMCONSOLE_NVIDIA_SMI` | `nvidia-smi` | command path (an absolute path may be given) |
| `rocm_smi` | `LLMCONSOLE_ROCM_SMI` | `rocm-smi` | AMD GPU tool |
| `journalctl` | `LLMCONSOLE_JOURNALCTL` | `journalctl` | log tool |
| `systemctl` | `LLMCONSOLE_SYSTEMCTL` | `systemctl` | service control tool |

**Typical values per inference framework:**

| Framework | `LLMCONSOLE_LLAMA_UNIT` | `LLMCONSOLE_LLAMA_BASE_URL` |
| --- | --- | --- |
| llama.cpp | `llama-server.service` | `http://127.0.0.1:8080` |
| Ollama | `ollama.service` | `http://127.0.0.1:11434` |
| vLLM | `vllm.service` | `http://127.0.0.1:8000` |
| SGLang | `sglang.service` | `http://127.0.0.1:30000` |

> The `llama` in these field names is historical (the project originally supported llama.cpp only).
> **It now means "any monitored inference service"** and has nothing to do with the detected framework.

---

## Service listening

| Field | Environment variable | Default | Notes |
| --- | --- | --- | --- |
| `host` | `LLMCONSOLE_HOST` | `0.0.0.0` | listen address |
| `port` | `LLMCONSOLE_PORT` | `8081` | listen port |

> Note: `uvicorn`'s `--host` / `--port` command-line arguments take precedence over these settings.

---

## Collection intervals and timeouts

| Field | Default | Notes |
| --- | --- | --- |
| `poll_interval_s` | `2.0` | main collection tick (slots, metrics, GPU) |
| `config_poll_interval_s` | `60.0` | model parameter polling (`/props` changes very slowly) |
| `pmon_interval_s` | `10.0` | process monitoring interval |
| `http_timeout_s` | `1.0` | regular HTTP timeout |
| `props_timeout_s` | `3.0` | `/props` timeout (it answers more slowly) |
| `cmd_timeout_s` | `2.0` | external command timeout |
| `cmd_kill_grace_s` | `3.0` | grace period after a timeout, waiting for the process to exit |
| `framework_redetect_s` | `30.0` | **retry interval when framework detection fails** (v0.5) |

> Before tuning the collection intervals, keep the console's **own overhead** in mind: the budget is
> CPU < 2% and memory < 200 MB. Collecting too often eats into the inference service's resources.

---

## Alert thresholds

| Field | Default | Notes |
| --- | --- | --- |
| `gpu_temp_warn_c` | `83.0` | GPU temperature warning |
| `gpu_temp_crit_c` | `87.0` | GPU temperature critical |
| `gpu_temp_sustain_s` | `120.0` | how long it must persist before alerting (debounce) |
| `vram_warn_pct` | `90.0` | VRAM usage warning |
| `vram_crit_pct` | `95.0` | VRAM usage critical |
| `vram_color_warn_pct` | `85.0` | threshold for the card to change colour (separate from alerting) |
| `kv_warn_pct` | `85.0` | KV capacity warning |
| `kv_crit_pct` | `95.0` | KV capacity critical |
| `kv_sustain_s` | `60.0` | KV alert debounce |
| `power_warn_pct` | `90.0` | power draw as a share of **that card's own** `power_limit` |
| `mtp_drop_ratio` | `0.80` | share of the baseline the MTP acceptance rate may fall to |
| `mtp_sustain_s` | `300.0` | MTP alert debounce |
| `decode_drop_ratio` | `0.50` | share of the baseline the decode throughput may fall to |
| `decode_sustain_s` | `300.0` | throughput alert debounce |
| `service_down_ticks` | `2` | consecutive failed probes before the service counts as unavailable |
| `event_alert_ttl_s` | `60.0` | **auto-recovery window for event alerts** (0 = never recover automatically, not recommended) |

> **The power alert is relative**: it is computed against each card's own `power_limit` rather than an
> absolute value — power ceilings differ greatly between models.

### Baseline overrides (learned automatically by default)

| Field | Default | Notes |
| --- | --- | --- |
| `mtp_accept_baseline` | `None` | `None` = use the learned value; a number overrides it by hand |
| `decode_baseline_tps` | `None` | same as above |

**Keeping `None` is strongly recommended.** A hard-coded baseline keeps raising false alerts after you
change machine or model.

---

## Automatic baseline learning

| Field | Default | Notes |
| --- | --- | --- |
| `baseline_warmup_s` | `600.0` | warm-up period before learning starts |
| `baseline_min_samples` | `20` | minimum number of samples |
| `baseline_quantile` | `0.50` | quantile to take (0.5 = median) |
| `baseline_persist_path` | `""` | persistence path; empty = `state/baseline.json` |
| `baseline_relearn` | `False` | set to `True` to discard the learned baseline and learn again |

How to relearn the baseline:

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

---

## Hardware and software stack inventory

| Field | Default | Notes |
| --- | --- | --- |
| `hardware_ttl_s` | `600.0` | how long inventory results are cached (hardware changes slowly) |
| `hw_cmd_timeout_s` | `3.0` | timeout for a single inventory command |
| `hw_cache_path` | `""` | cache path; empty = `state/hardware.json` |
| `hw_external_python` | `""` | use the given Python to probe PyTorch etc. (for machines with several environments) |
| `hw_enable_smartctl` | `False` | whether to read disk health with `smartctl` (needs root) |
| `hw_show_launch_args` | `False` | whether to show the inference service's full launch arguments on the page |
| `accel_vendor_allowlist` | `("10de", "1002")` | accepted accelerator PCI vendor IDs (NVIDIA / AMD) |
| `accel_pci_denylist` | `("1234:1111",)` | virtual GPUs that are explicitly excluded (QEMU etc.) |

### Adding a new accelerator vendor

Just add the new PCI vendor ID to `accel_vendor_allowlist`; no code change is needed:

```bash
# Show the GPU PCI IDs on this machine
lspci -nn | grep -iE 'vga|3d|display'
```

```ini
LLMCONSOLE_ACCEL_VENDOR_ALLOWLIST=["10de","1002","1ed5"]
```

> This field is a tuple, so **the environment variable must be written as a JSON array**; editing
> `.env` is more convenient.

### Making PyTorch from conda or another environment visible to the console

```ini
LLMCONSOLE_HW_EXTERNAL_PYTHON=/opt/conda/bin/python
```

---

## KV capacity determination

| Field | Default | Notes |
| --- | --- | --- |
| `kv_mode_override` | `""` | empty = determine automatically; may force `"unified"` / `"per_slot"` |
| `kv_quant_show_default` | `True` | whether to show "f16 (default)" when no quantisation is configured; `False` shows "unknown" |

The capacity mode is determined in this order:
**manual override → the `-kvu` argument in the unit file → the `-c` arithmetic relationship → logs → unknown**.

When it cannot be determined, the console shows "capacity mode unknown" rather than guessing — a wrong
guess throws the KV headroom completely off.

---

## Service control

| Field | Default | Notes |
| --- | --- | --- |
| `service_actions` | `("restart", "stop", "start")` | actions the page is allowed to trigger |
| `restart_eta_seconds` | `150` | estimated restart duration shown on the page |
| `service_poll_interval_s` | `30.0` | service state polling interval (`systemctl show` costs something, so it is rate-limited) |

To **disable service control entirely**, set `service_actions` to an empty array:

```ini
LLMCONSOLE_SERVICE_ACTIONS=[]
```

and do not install the sudoers allowlist.

---

## Alert log

| Field | Default | Notes |
| --- | --- | --- |
| `alert_log_default_limit` | `500` | number of entries shown by default |
| `alert_log_ring_max` | `2000` | in-memory ring buffer limit |
| `alert_log_file_max` | `10000` | trim threshold for the on-disk file |
| `alert_log_path` | `""` | persistence path; empty = `state/alert_log.jsonl` |

---

## Service log history

| Field | Default | Notes |
| --- | --- | --- |
| `log_history_days_options` | `(1, 7, 30)` | the range buttons on the page |
| `log_history_default_days` | `30` | default range |
| `log_history_max_lines` | `15000` | hard upper bound on lines per query |
| `log_history_default_limit` | `15000` | lines fetched per request |
| `log_history_timeout_s` | `30.0` | query timeout |
| `log_history_ttl_s` | `60.0` | how long results are cached |
| `log_history_live_max_lines` | `3000` | retention limit for the live section |
| `log_history_live_enabled` | `True` | whether the page may enable the live log |

> **`log_history_default_limit` must be ≥ the number of lines the largest range can produce.**
> Otherwise `journalctl -n` truncates from the "oldest" side, which looks like "I selected 30 days but
> only 1 day is covered".
> This is a pothole we really hit; `tests/test_defect_ledger.py::test_d3_*` guards against it.

---

## Multi-language

| Field | Default | Notes |
| --- | --- | --- |
| `default_lang` | `"auto"` | `auto` = follow the browser; `zh` / `en` = fixed |
| `supported_langs` | `("zh", "en")` | list of supported languages |
| `lang_fallback` | `"zh"` | fallback when browser language detection fails |

Language resolution order:
**the manual choice in `localStorage` (permanent) → `navigator.languages` → fallback**.

To make every visitor see English by default:

```ini
LLMCONSOLE_DEFAULT_LANG=en
```

---

## Buffers and backpressure

| Field | Default | Notes |
| --- | --- | --- |
| `history_points` | `150` | data points kept for the charts (150 points ≈ 5 minutes) |
| `log_queue_max` | `2000` | log queue limit |
| `log_ring_max` | `1000` | page log ring buffer |
| `ws_queue_max` | `100` | send queue limit per WebSocket connection |
| `ws_send_timeout_s` | `5.0` | WebSocket send timeout (slow clients are disconnected) |
| `ws_ping_interval_s` | `30.0` | heartbeat interval |
| `journal_backfill_lines` | `40` | log lines backfilled on the first connection |
| `journal_since` | `"-7d"` | scan window for the first backfill |
| `stream_reader_limit` | `1048576` | buffer limit for streaming reads |
| `stale_after_misses` | `3` | consecutive failed collections before data counts as stale |

---

## Self-overhead guards

| Field | Default | Notes |
| --- | --- | --- |
| `self_cpu_warn_pct` | `2.0` | warning line for the console's own CPU usage |
| `self_rss_warn_mb` | `200.0` | warning line for the console's own memory usage |
| `cmd_slow_ms` | `400.0` | an external command taking longer than this is recorded as a slow call |

---

## Runtime paths

| Field | Default | Notes |
| --- | --- | --- |
| `state_dir` | project root `state/` | state files (baseline, alert log, log cursor) |
| `static_dir` | project root `static/` | frontend static assets |
| `releases_dir` | project root `releases/` | release directory |

> At deployment time the unit file sets `state_dir` through `LLMCONSOLE_STATE_DIR` to
> `<deployment root>/state`, so that state survives a release symlink switch.

---

## Branding and attribution

| Field | Default | Notes |
| --- | --- | --- |
| `product_version` | `v0.5` | **the single source of truth for the version number** |
| `product_name` | `WKL-LLM Ops Platformv0.5` | header mark |
| `product_name_spaced` | `WKL-LLM Ops Platform v0.5` | version with a space |
| `developer` | `WKL-LLM Ops Platform` | developer line in the footer |
| `develop_date` | `2026.10.01` | development date |

**Rebranding for a derived project**: change only these fields; the frontend follows automatically
(there is no hard-coded version number or brand name anywhere in the frontend).

```ini
LLMCONSOLE_PRODUCT_VERSION=v1.0
LLMCONSOLE_PRODUCT_NAME=MyOpsPlatformv1.0
LLMCONSOLE_PRODUCT_NAME_SPACED=MyOpsPlatform v1.0
LLMCONSOLE_DEVELOPER=Example Corp
```

> The guard `tests/test_v043_features.py::test_page_scripts_have_no_version_literal`
> prevents a hard-coded version number in the frontend.

---

## Debugging

```ini
LLMCONSOLE_LOG_LEVEL=DEBUG
```

The log level is the `log_level` setting (`LLMCONSOLE_LOG_LEVEL`, also valid in `.env`). Allowed
values are `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`; `app/logging_setup.py` applies it.

Framework detection probe details are logged at `DEBUG` level, which is how you investigate
"why was it detected as unknown".
