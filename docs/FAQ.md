# FAQ

[中文](FAQ.zh-CN.md) · **English** · [Project home](../README.md) · [Installation](INSTALL.md)

## Installation and deployment

### Is Windows or macOS supported for deployment?

**No.** The console relies on systemd and journald to read service state and logs, and uses
`nvidia-smi` / `lscpu` / `lsblk` for hardware inventory. None of these exist on Windows/macOS.

**You can still develop on Windows/macOS**: the unit tests do not need those commands (every collector
has pure-function parsing tests). It is just that most panels show "not detected" once it runs.

### Must it run on the same machine as the inference service?

**Strongly recommended.** The console gets its data from:

- the inference service's HTTP API (may be remote)
- `systemd` unit state (**must be same host**)
- `journalctl` logs (**must be same host**)
- `nvidia-smi` GPU information (**must be same host**)

In a cross-machine deployment the last three all stop working, and the console degrades into
"HTTP metrics only".

### Why is `--workers 1` mandatory?

The console keeps four kinds of state **inside the process**:

| State | Notes |
| --- | --- |
| journalctl follower | one child process + cursor file |
| WebSocket broadcast | connection set |
| Hardware inventory cache | memory |
| Baseline learning | memory + on disk |

Multiple workers would each pull their own journalctl stream and keep their own connection set —
wasting resources and making the page data inconsistent (different requests land on different workers).

The collection volume itself is small (about 88 MB of memory), so a single worker is entirely enough.

### What if port 8081 is already in use?

Just change the configuration:

```ini
LLMCONSOLE_PORT=9090
```

But note: uvicorn's `--port` command-line argument **takes precedence over** this setting.
In a systemd deployment both live in the unit file (the `--port` in `ExecStart` and the `Environment`
line).

---

## Inference framework detection

### What if the "framework" chip at the top says "not identified"?

It means none of the candidate endpoints answered. Check in this order:

```bash
# 1. Is the inference service running?
systemctl status <your-inference-unit>

# 2. Is the HTTP address right? (default 8080, Ollama 11434, vLLM 8000)
curl -s http://127.0.0.1:8080/health

# 3. Look at the console's probe details (HTTP status per path)
journalctl -u llm-console.service -n 50 | grep -i framework
```

`framework.probes` in `/api/overview` lists the status code of every probe path, so you can see
directly which path answered and which returned 404.

**Common causes:**

| Symptom | Cause | Fix |
| --- | --- | --- |
| every path fails | wrong HTTP address | change `LLMCONSOLE_LLAMA_BASE_URL` |
| every path fails | the inference service only listens on a unix socket | switch it to a TCP listen, or put a reverse proxy in front |
| `/props` answers but it is detected as openai-compatible | it is not llama.cpp but another framework | normal, this is the fallback detection |
| everything is 404 | Ollama is installed but 8080 is being probed | Ollama defaults to **11434** |

### What does being detected as "openai-compatible" mean?

It means **only the OpenAI-compatible API was recognised, not which specific framework it is**.

The console's order of judgement is "proprietary signals first, generic fallback last". Landing in this
tier means none of the candidate proprietary endpoints (`/props`, `/api/version`, `/get_model_info`,
`/version`) matched.

In that state model parameters and per-slot detail are unavailable, but everything related to
`/v1/models` is still displayed.

If you use a framework this project already supports and still land in this tier, please open an issue
including the contents of `framework.probes` — it usually means that version of the framework changed
its endpoints.

### How do I support a new inference framework?

Add one entry to the `SPECS` data table in `app/services/framework.py`; **no `if` branch is needed**:

```python
FrameworkSpec(
    id="myframework",
    name_zh="<Chinese display name>",
    name_en="My Framework",
    require_paths=("/my/version",),          # paths that must be reachable
    match=(("/my/version", "version"),),      # detection signal: this JSON key being present is a match
    version_path="/my/version",
    version_keys=("version",),
    capabilities=frozenset({CAP_MODELS, CAP_HEALTH}),
    metrics_prefix="myfw:",
    # metric concepts the console understands → this framework's series names.
    # Anything you leave out is reported as unavailable, never guessed.
    metrics_map={
        M_TOKENS_GENERATED: ("myfw:tokens_generated_total",),
        M_REQUESTS_WAITING: ("myfw:requests_waiting",),
    },
    note_zh="<Chinese note>",
    note_en="My framework has no /slots; per-slot detail is unavailable",
)
```

Then add a fake-response test following the pattern in `tests/test_framework.py`.

### Why is there no "slots" panel for Ollama/vLLM/SGLang?

Because they **do not provide** a slot-level endpoint such as `/slots`. This is not a defect, it is a
difference in framework capabilities.

The console states plainly that "the current inference framework does not provide a slots endpoint"
instead of showing an empty table or falsely reporting degradation.

---

## Data and display

### Why does "service log history" cover only 12 days when I select 30?

`covered_days` on the page is the number of days **actually covered**, and it will be smaller than the
range you selected. The usual cause: the monitored service itself does not have logs that old.

```bash
# Find the oldest log entry of that unit
journalctl -u <inference-service> --no-pager -o short-iso | head -1
```

If the unit was created only recently, the 30-day range can naturally only return logs from after its
creation. **The console reports this honestly and does not claim 30 days of coverage.**

### Why is the disk capacity displayed so large?

The console de-duplicates by **block device**. systemd's `ProtectSystem` / `ReadWritePaths` bind-mount
the same partition at several paths, so counting by mount point double-counts.

If you see a clearly wrong capacity, please open an issue including the output of
`lsblk -o NAME,SIZE,MOUNTPOINT,TYPE`.

### Why is there no fan speed for the GPU?

**This is deliberate.** Data-centre cards (such as the Tesla series) return `[N/A]` when fan speed is
read through `nvidia-smi`. The console turns every `[N/A]` into "unknown" and **never into 0** —
otherwise it would raise a bogus "fan stopped" alert.

### KV headroom shows "capacity mode unknown"?

It means the console cannot determine the KV pool mode of the inference service. The order of
determination is:

**manual override → the `-kvu` argument in the unit file → the `-c` arithmetic relationship → logs → unknown**

When it cannot be determined it **shows unknown honestly instead of guessing** — a wrong guess throws
the KV headroom completely off.

To force it:

```ini
LLMCONSOLE_KV_MODE_OVERRIDE=unified    # or per_slot
```

### Alerts keep hanging and never disappear?

Both threshold alerts and event alerts **recover automatically**:

| Type | Recovery condition |
| --- | --- |
| Threshold alert | the metric returns within the threshold |
| Event alert | nothing more happens for longer than `event_alert_ttl_s` (60 seconds by default) |

If an event alert does not clear, check whether `event_alert_ttl_s` has been set to `0`
(`0` = never recover automatically).

### Which baseline values are correct?

**Do not fill in baselines by hand.** Leave `mtp_accept_baseline` and `decode_baseline_tps` at `None`
and let the console learn on your own machine.

A hard-coded baseline keeps raising false alerts after you change machine, model or quantisation format.

To relearn:

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

---

## Security

### Why is there no login?

**This is a deliberate design trade-off.** The project targets single-machine intranet deployments;
adding authentication would increase deployment complexity (user store, sessions, password storage, ...)
for limited benefit.

Isolate it at the **network layer** instead:

- listen only on an intranet address
- put a reverse proxy (Nginx/Caddy) in front with Basic Auth or SSO
- **never expose 8081 to the public internet**

See the [Security Policy](../SECURITY.md) for details.

### Why are the service control buttons greyed out?

It means the sudo allowlist is not installed, or not installed correctly.

```bash
# Check the allowlist
sudo -n systemctl reset-failed <your-inference-unit> && echo "allowlist active"

# Reinstall
SUDO_PW='...' LLM_INFER_UNIT=<your-inference-unit> bash deploy/install_sudoers.sh
```

**If you do not need this feature, do not install it** — read-only is safer.

### Why does the unit file relax systemd hardening?

Because three hardening settings conflict directly with functionality; the unit file documents the
reason for each of them:

| Setting | Conflict |
| --- | --- |
| `NoNewPrivileges=no` | `yes` disables the setuid bit, so `sudo` cannot elevate |
| `PrivateDevices=no` | `yes` makes `/dev/nvidia*` disappear and `nvidia-smi` fails |
| non-empty `CapabilityBoundingSet` | once emptied, `sudo` cannot get `CAP_SETUID`/`CAP_SETGID` |
| `ProtectProc=default` | `invisible` hides the inference process from psutil |

**When you do not need service control**, reverting to the recommended values gives better security.

---

## Development

### `selfcheck.sh` fails the format check, but the code looks fine

When developing on Windows, editors/Python write **CRLF** line endings by default. Once the files reach
Linux:

- shell scripts fail immediately with `set: pipefail: invalid option name`
- extensionless configuration files (such as sudoers) **stop working entirely**
- `ruff format --check` fails as well

```bash
python tools/fix_line_endings.py          # normalise to LF
python tools/fix_line_endings.py --check  # check only
```

### Why is the `ASYNC` rule set enabled in ruff?

It **statically catches** mistakes such as calling `subprocess.run` or `time.sleep` inside an `async def`.
Such problems are completely invisible at runtime and only show up as occasional stalls, which are
extremely hard to diagnose. The `ASYNC` rule set stops them at the CI stage.

### A guard raised a false positive because a comment contains example code

**Source-scanning guards must strip comments before matching.** See `tests/test_defect_ledger.py`:

```python
_strip_py(src)   # strip Python comments and docstrings
_code(src)       # keep executable code only
```

Using `src.find("if not fields:")` directly matches the example inside the comment and produces a wrong
conclusion.

### How do I generate a Word version of the docs?

The `.md` documents in this project can be converted to `.docx` with a bundled tool:

```bash
./venv/bin/pip install -e '.[docs]'
./venv/bin/python tools/md2docx.py input.md output.docx "header text"
```

The tool handles Chinese typesetting details (for example it inserts line-break opportunities only
inside ASCII tokens, avoiding zero-width spaces being inserted into Chinese text and corrupting it).

### Why does the frontend not use React/Vue?

Monitored machines usually **have no Node.js**. Using a framework would mean a build step, and therefore
either build output in the release or asking users to install Node.

Plain JavaScript keeps this project at "`git clone` and run".

### Why does the frontend contain not a single image?

Zero image assets is a hard constraint:

- no extra files needed to deploy
- no image caching or path handling to deal with
- every dark-theme icon is done with CSS/Unicode

The guard `deploy/check_frontend.py` blocks `<img>`, `background-image` and external `url(...)`.

---

## Other

### How does this project relate to enterprise observability platforms (Prometheus + Grafana)?

**It is not a replacement.** This project is positioned as **single-machine, lightweight and
zero-dependency**:

- Prometheus + Grafana suits many machines, long-term storage and complex queries, but needs a whole
  set of components deployed
- this project suits "one machine, and I want a quick look once it is up": `git clone` plus one command

If your inference cluster already has a multi-machine monitoring system, this project may not be
necessary. But if you are "one machine, and I do not want to install a whole stack just to look at VRAM",
it was written for exactly that.

### Can I look at the inference service only, without collecting host information?

There is no fine-grained switch at the moment. But you can:

- remove the accelerator from `accel_vendor_allowlist` (it will show "not detected")
- turning off unneeded panels requires changing frontend code; a PR to discuss it is welcome

### Will the project keep being maintained?

See the [Changelog](../CHANGELOG.md) and the issue tracker. PRs are welcome.
