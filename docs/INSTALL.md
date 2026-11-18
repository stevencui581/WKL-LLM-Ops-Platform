# Installation

[中文](INSTALL.zh-CN.md) · **English** · [Project home](../README.md) · [Configuration](CONFIGURATION.md) · [FAQ](FAQ.md)

> **Every command in this document is copy-paste ready.** Nothing needs editing unless it is
> wrapped in `<angle brackets>`, which marks a value specific to your environment.

## Contents

- [1. Operating system requirements](#1-operating-system-requirements)
- [2. Dependency requirements](#2-dependency-requirements)
- [3. Quick install (recommended)](#3-quick-install-recommended)
- [4. Manual install (step by step)](#4-manual-install-step-by-step)
- [5. Verify the installation](#5-verify-the-installation)
- [6. Run as a systemd service (optional)](#6-run-as-a-systemd-service-optional)
- [7. Upgrade](#7-upgrade)
- [8. Uninstall](#8-uninstall)
- [9. Installation troubleshooting](#9-installation-troubleshooting)

---

## 1. Operating system requirements

### 1.1 Supported systems

| System | Version | Status |
| --- | --- | --- |
| Ubuntu | 22.04 / 24.04 LTS | ✅ Tested |
| Debian | 12 (Bookworm) and newer | ✅ Tested |
| Rocky Linux / AlmaLinux / RHEL | 9 and newer | ✅ Supported |
| Fedora | 39 and newer | ✅ Supported |
| openEuler / Kylin / UOS | Recent releases | ⚠️ Not fully tested, usually works |
| Other Linux with systemd | — | ⚠️ Untested, usually works |
| **Windows / macOS** | — | ❌ **Not supported for deployment** |

> **Why Linux is required**: the platform reads inference-service state through `systemd`,
> service logs through `journald`, and GPU data through `nvidia-smi`. None of these exist on
> Windows or macOS.
>
> You **can** develop on Windows/macOS: the unit tests do not need those commands. The running
> console will simply show "not detected" for most panels.

### 1.2 Hard prerequisites

| Item | Requirement | Check |
| --- | --- | --- |
| Init system | **systemd** (mandatory) | `systemctl --version` |
| Permissions | Read access to journald (member of `systemd-journal` or `adm`) | `id -nG \| tr ' ' '\n' \| grep -E 'systemd-journal\|adm'` |
| Network | Access to PyPI (offline install: see §4.4) | `curl -I https://pypi.org` |
| Disk | About **300 MB** (venv + source + state) | `df -h .` |
| Memory | About **200 MB** free (the console itself uses ~88 MB) | `free -m` |

**Check whether your host qualifies (copy-paste):**

```bash
# OS and kernel
uname -s && grep -E '^(NAME|VERSION)=' /etc/os-release

# systemd present?
systemctl --version | head -1

# journald readable?
id -nG | tr ' ' '\n' | grep -E '^(systemd-journal|adm)$' && echo "OK: logs readable" || echo "WARN: group membership needed (see below)"

# Disk and memory
df -h . | tail -1
free -m | head -2
```

**If journald is not readable** (the log panel would stay empty):

```bash
sudo usermod -aG systemd-journal "$USER"
# Log out and back in (or reboot) for the group change to take effect
```

### 1.3 What you do *not* need (common misconceptions)

| Not required | Why |
| --- | --- |
| ❌ Docker / Kubernetes | Single-process deployment, runs directly on the host |
| ❌ Node.js | The frontend is plain JavaScript with **no build step** |
| ❌ Nginx / reverse proxy | The platform serves HTTP itself; a proxy is optional for auth |
| ❌ A database | State lives in local JSON / JSONL files |
| ❌ A GPU driver | It starts without a GPU; the accelerator panel just shows "not detected" |
| ❌ root | Installation needs no root; only the systemd unit does (sudo) |

---

## 2. Dependency requirements

### 2.1 Required dependencies

| Dependency | Version | Purpose | If missing |
| --- | --- | --- | --- |
| **Python** | **≥ 3.12** | Runs the backend | Cannot start |
| **python3-venv** | Matching Python | Creates the virtualenv | Cannot isolate dependencies; without `ensurepip` the venv has no pip |
| **pip** | ≥ 22 | Installs packages | Cannot install |
| **systemd** | Any recent | Service state, start on boot | Cannot read inference-service state |
| **journalctl** | Ships with systemd | Reads service logs | Log panel stays empty |
| **git** | Any | Fetches the source (a tarball also works) | Cannot clone |

### 2.2 Python packages (installed automatically by the installer)

Runtime dependencies are declared in `pyproject.toml`:

| Package | Version | Purpose |
| --- | --- | --- |
| `fastapi` | ≥ 0.115 | Web framework |
| `uvicorn[standard]` | ≥ 0.30 | ASGI server (includes WebSocket support) |
| `httpx` | ≥ 0.27 | Talks to the inference server's HTTP API |
| `psutil` | ≥ 5.9 | Process and system metrics |
| `pydantic-settings` | ≥ 2.4 | Configuration loading |

**Optional extras** (the console works fine without them):

| Package | Install | Purpose |
| --- | --- | --- |
| `python-docx` | `pip install -e '.[docs]'` | Markdown → Word export |
| `paramiko` | `pip install -e '.[remote]'` | Remote deploy helpers |
| `pytest` `ruff` `mypy` … | `pip install -e '.[dev]'` | Development and testing |

### 2.3 External commands (optional; each affects one panel only)

| Command | Provided by | Affected panel |
| --- | --- | --- |
| `nvidia-smi` | NVIDIA driver | GPU temperature / power / VRAM / utilisation |
| `rocm-smi` | AMD ROCm | AMD GPU information |
| `lscpu` `lsblk` `free` | util-linux / procps | Hardware inventory (present almost everywhere) |
| `nvcc` | CUDA Toolkit | CUDA version (also readable from `version.json`) |
| `smartctl` | smartmontools | Disk health (disabled by default) |

> **A missing command is not an error.** The platform's rule is:
> **a successful probe shows the real value, a failed probe shows "unknown", and an absent
> component shows "not installed" — it never substitutes a default.**

### 2.4 One-shot dependency check (copy-paste)

```bash
echo "== Python =="; for p in python3.13 python3.12 python3; do command -v $p >/dev/null && echo "  $p -> $($p -V 2>&1)"; done
echo "== venv =="; python3 -c 'import venv; print("  OK: venv available")' 2>/dev/null || echo "  MISSING: venv"
echo "== pip =="; python3 -m pip --version 2>/dev/null || echo "  MISSING: pip"
echo "== systemd =="; systemctl --version 2>/dev/null | head -1 || echo "  MISSING: systemd (unsupported)"
echo "== git =="; git --version 2>/dev/null || echo "  WARN: no git (a tarball works too)"
echo "== nvidia-smi =="; nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -3 || echo "  WARN: not installed (GPU panel only)"
```

### 2.5 Installing what is missing

**Ubuntu / Debian:**

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git util-linux procps curl
```

**Rocky / AlmaLinux / RHEL / Fedora:**

```bash
sudo dnf install -y python3.12 python3.12-pip git util-linux procps-ng curl
```

**openEuler / Kylin / UOS (yum-based):**

```bash
sudo yum install -y python3 python3-pip git util-linux procps-ng curl
```

**Note:** the `-venv` package must match the Python version you actually use. Ubuntu 26.04
ships Python 3.14, so the package name is `python3.14-venv` — not `python3.12-venv`. Verify it
with `python3 -m ensurepip --version` before creating the virtualenv.

> **Python 3.12 is not in your distribution's repos?** Three options:
> 1. `deadsnakes` (Ubuntu): `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv`
> 2. `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12`
> 3. Build from source: <https://www.python.org/downloads/>

---

## 3. Quick install (recommended)

### 3.1 Shortest path: one command

**Copy the line below, paste it into a terminal, press Enter:**

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
```

The script checks the OS, checks dependencies, downloads the source, creates a virtualenv,
installs dependencies, writes a config, runs a self-check, and **prints the start command**.

**Already cloned the repo?**

```bash
cd WKL-LLM-Ops-Platform && bash install.sh
```

### 3.2 Point it at your inference server (recommended)

Tell the installer which inference service to monitor, and you will not have to edit any config:

```bash
# llama.cpp (default port 8080)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service

# Ollama (default port 11434)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit ollama.service --infer-url http://127.0.0.1:11434

# vLLM (default port 8000)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit vllm.service --infer-url http://127.0.0.1:8000

# SGLang (default port 30000)
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit sglang.service --infer-url http://127.0.0.1:30000
```

Not sure of the unit name? Look it up:

```bash
systemctl list-units --type=service --state=running \
  | grep -iE 'llama|ollama|vllm|sglang|infer'
```

### 3.3 Install and register as a systemd service

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh \
  | bash -s -- --infer-unit llama-server.service --install-service -y
```

> Registering the service needs sudo. The installer calls `deploy/install_service.sh`, which
> renders the `__USER__` / `__ROOT__` / `__INFER_UNIT__` placeholders for your environment and
> writes the result to `/etc/systemd/system/`.

### 3.4 All installer options

```bash
bash install.sh --help
```

| Option | Meaning |
| --- | --- |
| `--port <port>` | Console port (default 8081) |
| `--infer-unit <unit>` | systemd unit of the inference service |
| `--infer-url <url>` | Inference service base URL |
| `--install-service` | Also install a systemd unit (needs sudo) |
| `--skip-deps` | Skip dependency installation (offline hosts) |
| `-y, --yes` | Non-interactive; accept all defaults |
| `-h, --help` | Show help |

Environment variables: `WKL_LANG=zh|en`, `WKL_PORT`, `WKL_INFER_UNIT`, `WKL_INFER_URL`,
`WKL_INSTALL_DIR`, `SUDO_PW`.

### 3.5 Start

```bash
cd ~/WKL-LLM-Ops-Platform                     # or your chosen install directory
./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1
```

Open `http://<server-ip>:8081`.

> ⚠️ **`--workers 1` is mandatory.** The console keeps a journalctl follower, WebSocket
> broadcast and hardware cache in process memory; multiple workers split that state.

---

## 4. Manual install (step by step)

Use this if you prefer not to run a script, or if the script cannot run in your environment.
**Every step lists the expected output — if it does not match, that step failed.**

### 4.1 Pick a directory and fetch the source

```bash
# 1) Choose an install directory (example: your home directory)
cd "$HOME"

# 2) Fetch the source (either way)
git clone https://github.com/stevencui581/WKL-LLM-Ops-Platform.git
cd WKL-LLM-Ops-Platform
```

**No git?** Use the tarball:

```bash
curl -fsSL https://github.com/stevencui581/WKL-LLM-Ops-Platform/archive/refs/heads/main.tar.gz -o wkl.tar.gz
tar -xzf wkl.tar.gz
mv WKL-LLM-Ops-Platform-main WKL-LLM-Ops-Platform
cd WKL-LLM-Ops-Platform
```

**Expected:** `ls` shows `app/ static/ tests/ deploy/ pyproject.toml install.sh` and friends.

```bash
ls
```

### 4.2 Confirm Python ≥ 3.12

```bash
python3 -V
```

**Expected:** `Python 3.12.x` or newer.

**Very new distributions may ship a newer default** (Ubuntu 26.04 provides Python 3.14). That is
fine, but the matching `-venv` package must be installed — check it before creating the venv:

```bash
python3 -m ensurepip --version    # must print a version; "No module named ensurepip" = the -venv package is missing
```

If `python3 -V` is older but `python3.12` exists:

```bash
python3.12 -V
# Use python3.12 instead of python3 everywhere below
```

**List all candidates at once:**

```bash
for p in python3.13 python3.12 python3; do
  command -v $p >/dev/null 2>&1 && echo "$p -> $($p -V 2>&1)"
done
```

### 4.3 Create the virtualenv

```bash
python3 -m venv venv
```

**Expected:** no output, and a `venv/` directory appears.

```bash
ls -d venv && echo "OK: virtualenv created"
```

**If you get `No module named venv`, or the new venv has no pip:**

```bash
# Install the -venv package that matches your Python version (example: 3.12)
sudo apt install -y python3.12-venv     # Ubuntu / Debian
sudo dnf install -y python3.12-pip      # RHEL family
```

**Always verify pip inside the venv before installing anything:**

```bash
./venv/bin/python -m pip --version      # must print a pip version
# If that fails, the venv is incomplete: delete it and recreate
rm -rf venv && python3 -m venv venv
```

### 4.4 Install dependencies

```bash
# Upgrade pip (optional but recommended)
./venv/bin/python -m pip install --upgrade pip

# Install runtime dependencies
./venv/bin/pip install -e .
```

**Expected:** the last line reads
`Successfully installed fastapi-... uvicorn-... httpx-... psutil-... pydantic-settings-...`

**Slow network / behind a firewall** — use a mirror:

```bash
./venv/bin/pip install -e . -i https://pypi.org/simple
```

**Offline / air-gapped hosts:** download the wheels elsewhere and copy them over:

```bash
# On a machine with network access (same arch and Python version)
pip download -d ./wheels -e .
# On the target host
./venv/bin/pip install --no-index --find-links=./wheels -e .
```

**If you see `error: command 'gcc' failed`:**

```bash
sudo apt install -y build-essential python3-dev     # Ubuntu / Debian
sudo dnf install -y gcc python3-devel               # RHEL family
```

### 4.5 Write the configuration

Ready-made profiles per framework (llama.cpp / Ollama / vLLM / SGLang) live in
[`examples/`](../examples/README.md) — copy one and edit the unit name:

```bash
cp examples/llama-cpp.env .env
```

Or create `.env` by hand:

```bash
cat > .env <<'EOF'
# systemd unit of the inference service (change to match your host)
LLMCONSOLE_LLAMA_UNIT=llama-server.service

# Inference service base URL
#   llama.cpp  http://127.0.0.1:8080
#   Ollama     http://127.0.0.1:11434
#   vLLM       http://127.0.0.1:8000
#   SGLang     http://127.0.0.1:30000
LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8080

# Console port
LLMCONSOLE_PORT=8081

# Log level: DEBUG / INFO / WARNING
LLMCONSOLE_LOG_LEVEL=INFO
EOF
```

**Expected:** `cat .env` prints the content above.

```bash
cat .env
```

> `.env` is listed in `.gitignore` and **is never committed**.
> See [Configuration](CONFIGURATION.md) for every available setting.

### 4.6 Verify

```bash
./venv/bin/python -c "import app.main; print('OK: backend imports')"
```

**Expected:** `OK: backend imports`

```bash
./venv/bin/python -c "from app.config import Settings; s=Settings(); print(s.product_name, s.product_version)"
```

**Expected:** `WKL-LLM运维平台v0.6 v0.6`

### 4.7 Start

**Foreground (best for watching logs and debugging):**

```bash
./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1 \
  --no-access-log --timeout-graceful-shutdown 30
```

**Expected output (the two lines that matter):**

```
INFO:     Uvicorn running on http://0.0.0.0:8081 (Press CTRL+C to quit)
INFO [main] framework: llama.cpp b11146 [health,metrics,models,props,slots]
```

The second line means **framework detection succeeded**. If it says `unknown`, see
[Troubleshooting](TROUBLESHOOTING.md).

**Background (temporary):**

```bash
mkdir -p logs
nohup ./venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8081 --workers 1 \
  > logs/console.log 2>&1 &
```

> Use systemd (see §6) for anything long-lived — `nohup` neither starts on boot nor restarts
> after a crash.

---

## 5. Verify the installation

All four should return `200`:

```bash
curl -s -o /dev/null -w 'live     = %{http_code}\n' http://127.0.0.1:8081/api/health/live
curl -s -o /dev/null -w 'ready    = %{http_code}\n' http://127.0.0.1:8081/api/health/ready
curl -s -o /dev/null -w 'overview = %{http_code}\n' http://127.0.0.1:8081/api/overview
curl -s -o /dev/null -w 'index    = %{http_code}\n' http://127.0.0.1:8081/
```

**Check framework detection (the most important one):**

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | ./venv/bin/python -c 'import json,sys; f=json.load(sys.stdin)["framework"]; print("framework:", f["id"], f["version"], f["capabilities"])'
```

**Expected:** `framework: llama.cpp b11146 ['health', 'metrics', 'models', 'props', 'slots']`

**Run the built-in diagnostics:**

```bash
./venv/bin/python probes/check_branding.py        # branding and version consistency
./venv/bin/python probes/diag_framework_chip.py   # framework detection pipeline
./venv/bin/python deploy/check_frontend.py        # frontend static checks
```

---

## 6. Run as a systemd service (optional)

Requires sudo. **Change the unit name to match your inference service:**

```bash
LLM_INFER_UNIT=llama-server.service \
SUDO_PW='<your-sudo-password>' \
  bash deploy/install_service.sh
```

Omit `SUDO_PW` when sudo needs no password.

The script creates `state/` `logs/` `releases/`, renders the unit template, runs
`systemd-analyze verify`, `daemon-reload`, `enable`, `restart`, probes the health endpoints and
prints a security score.

**Status and logs:**

```bash
systemctl status llm-console.service
journalctl -u llm-console.service -f
```

### Optional: allow restarting the inference service from the UI

By default the console is **read-only** with respect to the inference service. To enable the
restart/stop buttons, install the minimal sudo allowlist:

```bash
SUDO_PW='<your-sudo-password>' LLM_INFER_UNIT=llama-server.service \
  bash deploy/install_sudoers.sh
```

The allowlist permits **only four actions on the monitored unit**
(restart / stop / start / reset-failed) and no arbitrary `systemctl` command.
**Do not install it if you do not need it** — read-only is safer.
See [Security Policy](../SECURITY.md).

---

## 7. Upgrade

**One command:**

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/update.sh | bash
```

**From an existing checkout:**

```bash
cd WKL-LLM-Ops-Platform && bash update.sh
```

The script backs up `state/`, `logs/` and `.env`, runs `git pull`, updates dependencies, runs a
self-check and restarts the service. **Any failure rolls back** to the pre-upgrade revision.

Manual upgrade:

```bash
cd WKL-LLM-Ops-Platform
git pull
./venv/bin/pip install -e .
sudo systemctl restart llm-console.service     # if the unit is installed
```

> The project also ships a **versioned-directory release with an atomic symlink and a
> health-gated automatic rollback**: `bash deploy/deploy.sh` publishes, `bash deploy/rollback.sh`
> reverts in about a second. See [Architecture](ARCHITECTURE.md).

---

## 8. Uninstall

```bash
# Remove the service only (keep source and config)
bash uninstall.sh

# Remove source, virtualenv and state as well
bash uninstall.sh --purge
```

Manual removal:

```bash
SUDO_PW='<password>' bash deploy/install_sudoers.sh --remove   # if installed
sudo systemctl disable --now llm-console.service
sudo rm -f /etc/systemd/system/llm-console.service
sudo systemctl daemon-reload
rm -rf ~/WKL-LLM-Ops-Platform          # verify the path before running this
```

---

## 9. Installation troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Python 3.12 or newer is required` | Python too old | See [§2.5](#25-installing-what-is-missing) |
| `No module named venv` | python3-venv missing | `sudo apt install -y python3.12-venv` |
| `No module named pip` / `venv/bin/pip: No such file or directory` | The venv was created without pip (matching `python3.X-venv` / `ensurepip` missing) | Install `python3.X-venv` for **your** Python version, then `rm -rf venv && python3 -m venv venv` |
| `pip install` times out | Network | Add `-i https://pypi.org/simple` or a local mirror |
| `error: command 'gcc' failed` | Build tools missing | `sudo apt install -y build-essential python3-dev` |
| `Address already in use` | Port 8081 taken | `ss -lntp \| grep 8081` or change `LLMCONSOLE_PORT` |
| Page loads but every value shows "—" | Wrong URL or unit name | Check `LLMCONSOLE_LLAMA_BASE_URL` and `LLMCONSOLE_LLAMA_UNIT` in `.env` |
| Header shows "not identified" | Probe endpoints unreachable | `./venv/bin/python probes/diag_framework_chip.py` |
| Log panel is empty | No journald access | `sudo usermod -aG systemd-journal $USER`, then re-login |
| `set: pipefail: invalid option name` | Script has CRLF line endings | Re-clone; never edit `.sh` files with a Windows editor |
| systemd reports `masked` | Unit file written as 0 bytes | Re-run `bash deploy/install_service.sh` (fixed in this repo) |

**Still stuck?** See [Troubleshooting](TROUBLESHOOTING.md) and [FAQ](FAQ.md), or open an
[issue](https://github.com/stevencui581/WKL-LLM-Ops-Platform/issues).

---

**Next:** [Configuration](CONFIGURATION.md) · [Architecture](ARCHITECTURE.md) · [API](API.md)
