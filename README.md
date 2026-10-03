# ⚡ WKL-LLM Ops Platform

[![CI](https://github.com/stevencui581/WKL-LLM-Ops-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/stevencui581/WKL-LLM-Ops-Platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-v0.6-green.svg)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#-hardware-and-os-target)

Language: English | [简体中文](README.zh-CN.md)

A lightweight operations console for **locally hosted LLM inference servers** — health,
throughput, KV cache and alerts on a single page.

It aggregates what you would otherwise read from `nvidia-smi`, `/slots`, `/metrics` and
`journalctl` into one dark-theme static page, with **no frontend build step, no image assets and a
single-process deployment**. Every hardware, driver and framework fact is **probed at runtime** —
no machine model, path or model name is ever hard-coded.

Repository: [stevencui581/WKL-LLM-Ops-Platform](https://github.com/stevencui581/WKL-LLM-Ops-Platform)
Current baseline: `v0.6`
Release history: [CHANGELOG.md](CHANGELOG.md)
Documentation: [docs/](docs/README.md)

## 💡 Why This Exists

A single box serving llama.cpp, Ollama, vLLM or SGLang has four questions that must be answered at
the same time:

- How much context headroom is left before the KV cache OOMs?
- Are the GPUs thermally or electrically constrained?
- Has decode throughput drifted away from this machine's own baseline?
- Did the service exit, truncate a context, or did a client cancel?

The data is scattered across four tools with four output formats. This console answers all four on
one page, and runs on the same host so it can reach `systemd` and `journald` directly.

| What you would check manually | Where this console shows it |
| --- | --- |
| `nvidia-smi` | GPU temperature / power / VRAM / utilisation |
| `/slots` | per-slot context usage and prompt-cache hits |
| `/metrics` | throughput, MTP acceptance, token counters |
| `journalctl -u <unit>` | recent lines, 1 / 7 / 30-day history, download |
| `systemctl status <unit>` | service state, uptime, restart / stop / start |
| `lscpu`, `lsblk`, driver checks | hardware and software inventory |

## 🧩 Supported Inference Frameworks

The console identifies the running framework, its version and its API surface at startup.

| Framework | Detection signal | Version source | Per-slot detail |
| --- | --- | --- | --- |
| **llama.cpp** (`llama-server`) | `/props` contains `build_info` | `/props` → `build_info` | ✅ `/slots` |
| **Ollama** | `/api/version` | `/api/version` → `version` | ❌ not exposed |
| **vLLM** | `/version` + `/v1/models` | `/version` | ❌ not exposed |
| **SGLang** | `/get_model_info` | `/get_server_info` → `version` | ❌ not exposed |
| OpenAI-compatible | `/v1/models` | — | ❌ not exposed |
| Unidentified | all probes failed | — | — |

The result appears in the header, for example `Framework llama.cpp b11146`.

**When a framework does not expose an API, the console says so explicitly instead of showing an
empty panel or a false "degraded" alert.** Adding a framework means adding one entry to the `SPECS`
table in `app/services/framework.py` — there are no `if` branches anywhere else.

## 🚀 Install And Start

Requires Linux with **systemd** and **Python 3.12+**. One command does everything:

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
```

Point it at your inference service in the same command:

```bash
# llama.cpp (port 8080)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service
```

```bash
# Ollama (port 11434)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit ollama.service --infer-url http://127.0.0.1:11434
```

```bash
# vLLM (port 8000)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit vllm.service --infer-url http://127.0.0.1:8000
```

```bash
# SGLang (port 30000)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit sglang.service --infer-url http://127.0.0.1:30000
```

Then start it:

```bash
cd ~/WKL-LLM-Ops-Platform
./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers 1
```

Open `http://<server-ip>:8081`.

> ⚠️ **`--workers 1` is mandatory.** The console keeps a journalctl follower, a WebSocket
> connection set and hardware caches in process memory; multiple workers split that state. One
> worker handles this data volume comfortably (~88 MB).

To install it as a service that starts on boot:

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service --install-service -y
```

Upgrade and uninstall are equally short:

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/update.sh | bash
```

```bash
bash uninstall.sh            # remove the service, keep the source
bash uninstall.sh --purge    # remove everything
```

**Full instructions — including a step-by-step manual install and offline installation:**
[docs/INSTALL.md](docs/INSTALL.md)

## 🛠️ Hardware And OS Target

| Item | Requirement |
| --- | --- |
| OS | Linux with systemd: Ubuntu 22.04+ / Debian 12+ / RHEL 9+ / Fedora 39+ |
| Python | 3.12 or newer |
| Permission | Member of `systemd-journal` or `adm` to read logs |
| Disk | About 300 MB |
| Memory | About 200 MB free; the console itself uses about 88 MB |
| Inference server | llama.cpp / Ollama / vLLM / SGLang, on the same host |

Not required: Docker, Node.js, a database, a reverse proxy, a GPU driver, or root.

The console starts without a GPU and simply reports "not detected" for the accelerator panel. Every
hardware fact is probed at runtime, so moving to another machine needs no code changes.

## 🧪 Quality Evidence

```bash
bash selfcheck.sh            # ruff check + ruff format --check + mypy + pytest
bash deploy/verify_all.sh    # 10 end-to-end suites (requires a running service)
```

| Item | Status |
| --- | ---: |
| Unit tests | 425 tests |
| End-to-end suites | 10, all passing |
| Bilingual documentation guards | 56 |
| Repository consistency guards | 26 |
| mypy source files | 40 |
| Console memory use | 88 MB (budget 200 MB) |
| Frontend build steps | 0 |
| Frontend image assets | 0 |

## ❓ FAQ

**Does it support Windows or macOS?**
No. It reads service state from `systemd`, logs from `journald` and GPU data from `nvidia-smi`.
You can develop on those platforms, but most panels stay empty.

**Must the console run on the same host as the inference server?**
Strongly recommended. Only the HTTP API can be reached remotely; service state, logs and GPU data
cannot.

**The header says "not identified" — what now?**
Run `./venv/bin/python probes/diag_framework_chip.py`. It prints the HTTP status of every probe
path, which shows immediately whether the address is wrong or the port is wrong (Ollama uses 11434,
vLLM 8000, SGLang 30000).

**Why is there no per-slot panel for Ollama, vLLM or SGLang?**
They do not expose a slots API. That is a framework capability difference, not a defect, and the
console states it rather than showing an empty table.

**How do I add a framework you do not support yet?**
Add one `FrameworkSpec` row to `SPECS` in `app/services/framework.py` and one fake-response test.
No `if` branches are needed or accepted.

**Why do the alert thresholds look wrong for my machine?**
They may be. Baselines are auto-learned per machine; never hard-code them. If a baseline was learned
while the service was under load, delete `state/baseline.json` and restart.

**Is there any authentication?**
No. This is a deliberate trade-off for single-host internal deployments — isolate it at the network
layer. See [SECURITY.md](SECURITY.md).

**Why only 30 days of logs, and sometimes fewer?**
Your journald retention decides. The page reports the *actual* covered range, and never claims more
than it has.

More: [docs/FAQ.md](docs/FAQ.md) and [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## 🧭 Design Principles

1. **Every hardware fact is probed at runtime.** A failed probe shows *unknown*; a missing component
   shows *not installed*. Never substitute a default.
2. **Capabilities are gated per framework.** Switching frameworks means "this API is not collected",
   not "collection failed and the UI degraded".
3. **Data and presentation are separate.** The backend ships structured, language-neutral fields;
   the frontend owns language selection.
4. **Guards must be trustworthy.** Source-scanning guards strip comments before matching — a comment
   containing an example otherwise produces false confidence.
5. **A permanently red gate equals no gate.** One-off scripts are deleted, or explicitly exempted
   with a stated reason.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow and module breakdown.

## 📁 Repository Layout

```text
WKL-LLM-Ops-Platform/
├── install.sh              One-command installer (bilingual output)
├── update.sh               One-command upgrade with automatic rollback
├── uninstall.sh            One-command uninstall
├── app/                    Backend (FastAPI)
│   ├── services/
│   │   ├── framework.py    Inference framework detection
│   │   ├── aggregator.py   Collection fan-in and capability gating
│   │   └── alerts.py       Alert engine with auto-resolution
│   ├── collectors/         Per-source collectors (slots / metrics / hardware / logs)
│   └── routes/             REST and WebSocket endpoints
├── examples/               Ready-to-use .env profiles per framework
├── static/                 Frontend (plain JS, no build, no images)
├── tests/                  Unit tests and guards
├── probes/                 Live acceptance and diagnostics
├── deploy/                 Deploy, rollback and acceptance scripts
├── tools/                  Development helpers
└── docs/                   Documentation (English + Chinese)
```

## 🤝 Contributing

Issues and pull requests are welcome.

- [Contributing guide](CONTRIBUTING.md) ([中文](CONTRIBUTING.zh-CN.md))
- [Code of Conduct](CODE_OF_CONDUCT.md) ([中文](CODE_OF_CONDUCT.zh-CN.md))
- [Security policy](SECURITY.md) ([中文](SECURITY.zh-CN.md)) — do not open a public issue for
  vulnerabilities
- [AGENTS.md](AGENTS.md) — conventions for AI coding agents

## 🙏 Credits

- [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) — README structure and repository
  layout reference
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — multilingual README
  naming and one-command setup script reference
- [weicj/vLLM-2080Ti-Definitive](https://github.com/weicj/vLLM-2080Ti-Definitive) — layout and
  one-command script reference
- [OpenJS Foundation](https://github.com/openjs-foundation/cross-project-council) — community health
  file guidance
- [Contributor Covenant](https://www.contributor-covenant.org) — Code of Conduct

## 📄 License

[MIT](LICENSE)

---

<sub>Maintainer: WKL-LLM Ops Platform · Initial release 2026-10-01 · v0.6</sub>
