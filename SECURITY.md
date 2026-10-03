# Security Policy

[中文](SECURITY.zh-CN.md) · **English**

## Supported versions

Security fixes are applied to the latest release only.

| Version | Supported |
| --- | --- |
| v0.6.x | ✅ |
| < v0.6 | ❌ |

## Reporting a vulnerability

**Please do not report security vulnerabilities in a public issue.**

Open the repository's [Security tab](https://github.com/stevencui581/WKL-LLM-Ops-Platform/security)
and click **Report a vulnerability**, or go straight to
[the private advisory form](https://github.com/stevencui581/WKL-LLM-Ops-Platform/security/advisories/new).

GitHub's own guide:
[privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).

Please include:

- The affected version
- Reproduction steps (as specific as possible)
- The impact and any plausible exploit path
- A suggested fix if you have one

We will acknowledge within **7 days** and credit you once a fix is released (unless you prefer to
stay anonymous).

## Deployment security notes

This project is designed to run on a **trusted internal network**. Please understand the following.

### The console has no authentication

There is **no login**. Anyone who can reach `http://<host>:8081` can see the monitoring data and —
if service control is enabled — **restart or stop your inference service**.

Please:

- Bind it to an internal address only, or put it behind a reverse proxy with auth
- Do not expose port 8081 to the public internet
- If you do not need service control, do not install the sudoers allowlist (below)

### Service control relies on a minimal sudo allowlist

`deploy/install_sudoers.sh` installs `/etc/sudoers.d/llm-console`, which permits **only four
actions on the monitored unit** (`restart` / `stop` / `start` / `reset-failed`) and does **not**
permit arbitrary `systemctl` commands.

Remove it when you do not need the capability:

```bash
SUDO_PW='...' bash deploy/install_sudoers.sh --remove
```

### The unit file deliberately relaxes three systemd hardening settings

`deploy/llm-console.service` sets `NoNewPrivileges=no`, `PrivateDevices=no` and a non-empty
`CapabilityBoundingSet`, each with the reason recorded inline:

| Setting | Why it is relaxed |
| --- | --- |
| `NoNewPrivileges=no` | `yes` disables the setuid bit, so `sudo` cannot elevate and service control is permanently reported as "unauthorised" |
| `PrivateDevices=no` | `yes` hides `/dev/nvidia*` and `nvidia-smi` fails outright |
| Non-empty `CapabilityBoundingSet` | An empty set strips `CAP_SETUID`/`CAP_SETGID`, so a correctly configured allowlist still fails |
| `ProtectProc=default` | `invisible` hides the inference process from psutil |

**If you do not need service control**, revert these to the systemd-recommended values
(`NoNewPrivileges=yes`, empty `CapabilityBoundingSet`) for stronger isolation. Please note the
choice in your PR or deployment notes.

### Credentials never enter the repository

`deploy/host.env` is ignored by `.gitignore`. Please **do not** commit or paste your server
address, username or password into the repository, an issue, or a screenshot. See
`deploy/host.env.example` for the template.

## Known design trade-offs

| Trade-off | Rationale |
| --- | --- |
| No authentication | Aimed at single-host internal deployments; adding auth increases deployment complexity. Isolate at the network layer instead. |
| Service control needs sudo | A minimal allowlist constrains the risk to four actions on one unit |
| Collectors read journald | Requires membership of `systemd-journal` or `adm` |

If one of these trade-offs is unacceptable in your environment, please open an issue to discuss it.
