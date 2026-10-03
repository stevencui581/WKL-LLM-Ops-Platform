# Troubleshooting

[中文](TROUBLESHOOTING.zh-CN.md) · **English** · [Project home](../README.md) · [Installation](INSTALL.md)

This document is organised by **symptom**. Each entry gives: possible cause → diagnostic command → fix.

## Quick diagnostics

```bash
# 1. The console service itself
systemctl status llm-console.service
journalctl -u llm-console.service -n 50 --no-pager

# 2. The three health endpoints
curl -s -o /dev/null -w 'live=%{http_code}\n'     http://127.0.0.1:8081/api/health/live
curl -s -o /dev/null -w 'ready=%{http_code}\n'    http://127.0.0.1:8081/api/health/ready
curl -s -o /dev/null -w 'overview=%{http_code}\n' http://127.0.0.1:8081/api/overview

# 3. Readiness reasons (which item is preventing readiness)
curl -s http://127.0.0.1:8081/api/health | python3 -m json.tool

# 4. Framework detection result and probe details
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["framework"], ensure_ascii=False, indent=2))'
```

---

## The console will not start

### `systemctl status` shows `failed`, or the service restarts repeatedly

```bash
journalctl -u llm-console.service -n 100 --no-pager
```

| Log signature | Cause | Fix |
| --- | --- | --- |
| `Address already in use` | 8081 is taken | find the owner with `ss -lntp \| grep 8081`, or change the port |
| `ModuleNotFoundError` | dependencies not installed in the venv, or wrong path | check the Python path in `ExecStart` and `pip install -e .` again |
| `pydantic_core.ValidationError` | a misspelled configuration variable | `extra="forbid"` makes unknown variables fail loudly; correct it per the error message |
| `Permission denied` accessing state/ | wrong directory owner | `chown -R <runtime-user> state logs` |
| `reception only permitted for main PID` | unit file missing `NotifyAccess=all` | use the unit file template shipped in this repository |

### `systemctl status` shows `masked`

**This is a pothole we have hit.** When the unit file is written as 0 bytes, systemd treats it as masked.

Cause: piping the rendered result into `sudo -S tee` — `sudo -S` reads the password from stdin, the
piped content was swallowed by the password prompt, and an empty file was written.

```bash
# Confirm the file size
ls -la /etc/systemd/system/llm-console.service

# Reinstall (install_service.sh in this repository already fixes it: write a temp file first, then install)
LLM_INFER_UNIT=<your-inference-unit> SUDO_PW='...' bash deploy/install_service.sh
```

### The service starts but the page will not open

```bash
# Can this host reach it
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/

# Is the listen address right (0.0.0.0 vs 127.0.0.1)
ss -lntp | grep 8081

# Firewall
sudo ufw status        # or firewall-cmd --list-all
```

If listening on `0.0.0.0` works but external access does not, it is a firewall or security-group issue.

---

## The page is empty or shows odd values

### The whole page is nothing but "—"

It means `/api/overview` is not getting data. Check in order:

```bash
# Is the inference service running
systemctl status <your-inference-unit>

# Does the HTTP API answer (note the port: llama.cpp 8080 / Ollama 11434 / vLLM 8000 / SGLang 30000)
curl -s http://127.0.0.1:8080/health

# Is the address configured in the console right
systemctl show llm-console.service -p Environment
```

### The "framework" chip at the top says "not identified"

See the [FAQ](FAQ.md). The key diagnostic is `framework.probes` —
it lists the HTTP status of every candidate endpoint:

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["framework"]["probes"])'
```

`{"/props": 200, "/version": 0, "/api/version": 0}` means only `/props` answered (llama.cpp).

### The hardware panel says "not detected" although there obviously is a GPU

```bash
# Can the command the console uses run (note: use the user the console runs as)
sudo -u <runtime-user> nvidia-smi --query-gpu=index,name --format=csv,noheader

# Is the GPU's PCI ID in the allowlist
lspci -nn | grep -iE 'vga|3d|display'
```

- NVIDIA should be `10de`, AMD should be `1002`. Other vendors must be added to `accel_vendor_allowlist`.
- QEMU virtual GPUs (`1234:1111`) are excluded by default, and that is deliberate.

### The log panel is empty

```bash
# Is the unit name right
systemctl list-units --type=service | grep -iE 'llama|ollama|vllm|sglang'

# Does that unit have any logs
journalctl -u <your-inference-unit> -n 5 --no-pager

# Can the current user read journald
id    # needs the systemd-journal or adm group
```

The console runs as the user that deployed it. If that user is not in the `systemd-journal` / `adm`
group, it cannot read logs:

```bash
sudo usermod -aG systemd-journal <runtime-user>
sudo systemctl restart llm-console.service
```

### The log panel says "service running normally" but the inference service is clearly not running

```bash
systemctl is-active <your-inference-unit>
journalctl -u llm-console.service | grep -i 'unit\|service'
```

Check whether `LLMCONSOLE_LLAMA_UNIT` points at the real unit name.

---

## Performance problems

### The console's own CPU usage is high

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"])'
```

Budget: CPU < 2%, memory < 200 MB.

If you exceed it:

1. **Make sure there is only one worker** (`ps aux | grep uvicorn`). Multiple workers make each worker pull its own journalctl.
2. Raise `poll_interval_s` (2 seconds by default).
3. Raise `hardware_ttl_s` (600 seconds by default).
4. Check for slow commands: `journalctl -u llm-console.service | grep -i slow`.

### Memory keeps growing

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"]["rss_mb"])'
```

This project has in the past had **unbounded growth of the log history cache** (46 MB → 88 MB);
it was fixed with LRU eviction (limit 4 entries).

If you see sustained growth, record the information below and open an issue:

```bash
# Watch for 10 minutes, recording once a minute
for i in $(seq 1 10); do
  curl -s http://127.0.0.1:8081/api/overview \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["self"]["rss_mb"])'
  sleep 60
done
```

### The page stutters, or the WebSocket disconnects frequently

```bash
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["health"]["ws"])'
```

WebSockets have backpressure protection: the send queue per connection is capped by `ws_queue_max`
(100 by default) and the send timeout is `ws_send_timeout_s` (5 seconds by default). **Slow clients are
disconnected on purpose**; that is designed behaviour.

If healthy clients also disconnect frequently, look for network jitter (`ws_ping_interval_s` is
30 seconds by default).

---

## Alerts

### An alert never clears

| Type | Recovery condition |
| --- | --- |
| Threshold alert | the metric returns within the threshold |
| Event alert | nothing more happens for longer than `event_alert_ttl_s` (60 seconds by default) |

```bash
# Confirm the TTL setting
systemctl show llm-console.service -p Environment | tr ' ' '\n' | grep -i TTL
```

`event_alert_ttl_s=0` means **no automatic recovery** (not recommended).

### The alert log has only `raised` and no `resolved`

This used to be a real defect (automatic recovery of event alerts did not work).
If it still happens:

```bash
curl -s 'http://127.0.0.1:8081/api/alert-log?limit=20' | python3 -m json.tool | head -60
```

Please open an issue with the configured value of `event_alert_ttl_s` and the output above.

### False alerts (for example the throughput alert firing often)

The most likely cause is an **unsuitable baseline**. The baseline may have been learned in an abnormal
state (for example while the service was under a load test).

```bash
# Show the current baseline
curl -s http://127.0.0.1:8081/api/overview \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["baseline"])'
```

Relearn (do it while the service is **running normally**):

```bash
sudo systemctl stop llm-console.service
rm state/baseline.json
sudo systemctl start llm-console.service
```

Or relax the thresholds:

```ini
LLMCONSOLE_MTP_DROP_RATIO=0.70
LLMCONSOLE_DECODE_DROP_RATIO=0.40
```

---

## Service control is unavailable

### The buttons are greyed out

```bash
# Is the allowlist installed
sudo -n systemctl reset-failed <your-inference-unit> && echo "active" || echo "not active"

# The console's own verdict
curl -s http://127.0.0.1:8081/api/service/status | python3 -m json.tool
```

Reinstall the allowlist:

```bash
SUDO_PW='...' LLM_INFER_UNIT=<your-inference-unit> bash deploy/install_sudoers.sh
```

### The allowlist is installed but it reports "not authorized"

Check in order:

```bash
# 1. sudoers file syntax
sudo visudo -c -f /etc/sudoers.d/llm-console

# 2. Is the unit name written correctly (it must match exactly)
sudo cat /etc/sudoers.d/llm-console

# 3. Is NoNewPrivileges set to no in the unit file
systemctl show llm-console.service -p NoNewPrivileges

# 4. Is the capability bounding set empty (empty = sudo cannot get CAP_SETUID)
systemctl show llm-console.service -p CapabilityBoundingSet
```

If item 4 prints `CapabilityBoundingSet=` (empty), it must be changed back to a non-empty set —
see the [Security Policy](../SECURITY.md).

> One more note: `deploy/sudoers.llm-console` must use **LF** line endings.
> CRLF makes the sudoers parser fail, and the error from `visudo -c` is not necessarily obvious.
> CI and `python tools/fix_line_endings.py --check` catch this.

---

## Deployment and upgrade

### The page is unchanged after an upgrade

```bash
# See which version the symlink currently points at
ls -la current
systemctl show llm-console.service -p WorkingDirectory

# Browser cache: force a refresh (Ctrl+Shift+R)
# or query the API directly
curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; print(json.load(sys.stdin)["branding"]["product_version"])'
```

### The service is unhealthy after an upgrade

`deploy/deploy.sh` has a health gate and rolls back automatically on failure. Manual rollback:

```bash
bash deploy/rollback.sh
```

Rollback takes seconds (it only switches the symlink and restarts the service).

### I changed the code locally, but the fix on the server "disappeared"

**This was a real defect.** Cause: the directory list in the sync-back script was missing some
directories (such as `probes` and `tools`), so fixes made on the server could not be synced back, and
the next upload overwrote them with the unfixed version again — which looks like "my change had no
effect".

The current flow (`deploy/preflight.py`) fixes this:

```bash
python3 deploy/preflight.py    # upload → remote format + gates → sync back
```

**Do not** upload without syncing back, or the local and remote copies will diverge.

---

## Collection and data accuracy

### Disk capacity looks clearly too large

De-duplicated by block device. If the problem persists, please open an issue with the output of
`lsblk -o NAME,SIZE,MOUNTPOINT,TYPE`.

### VRAM/utilisation fluctuates wildly

It may be that the collection interval is too long (2 seconds by default), giving too few sample points.
You can lower `poll_interval_s`, but keep the self-overhead budget in mind.

### `[N/A]` is displayed as 0

**That should not happen.** This project's rule is that every `[N/A]` becomes "unknown" and **never 0**
(turning it into 0 would raise bogus low-power / zero-temperature alerts).

If you really do see 0, please open an issue with the raw collected value.

---

## Collecting diagnostic information

Before opening an issue, run the following; it packages the key information (**review it and remove
anything sensitive first**):

```bash
{
  echo "=== Version ==="
  curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["branding"])'
  echo "=== Framework ==="
  curl -s http://127.0.0.1:8081/api/overview | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["framework"], ensure_ascii=False))'
  echo "=== Health ==="
  curl -s http://127.0.0.1:8081/api/health
  echo
  echo "=== Service state ==="
  systemctl status llm-console.service --no-pager | head -20
  echo "=== Configuration ==="
  systemctl show llm-console.service -p Environment | tr ' ' '\n' | grep LLMCONSOLE
  echo "=== System ==="
  uname -a
  python3 -V
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo "no nvidia-smi"
  echo "=== Logs (last 50 lines) ==="
  journalctl -u llm-console.service -n 50 --no-pager
} > diag.txt 2>&1

echo "Diagnostics written to diag.txt; review them before uploading"
```
