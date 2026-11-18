# Changelog

**English** · [中文](CHANGELOG.zh-CN.md)

This project follows [Semantic Versioning](https://semver.org/) and the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

## [Unreleased]

### Fixed

- **Installer could reuse a broken virtualenv.** Where the matching `python3.X-venv` package is
  missing (for example Ubuntu 26.04 with Python 3.14), `python3 -m venv` leaves a venv with no
  `pip`. `install.sh` used to see the directory, "reuse" it, and then fail with
  `venv/bin/pip: No such file or directory`. It now checks `ensurepip`, verifies `pip` before
  reusing a venv, recreates incomplete ones, and always calls `python -m pip`.
- **Multi-framework metrics were never collected.** Metrics enablement was overwritten by the
  `/props` switch on every tick; vLLM/SGLang have no `/props`, so their `/metrics` was never read.
  Series names were also hard-coded to `llamacpp:*`, so `vllm:*` / `sglang:*` were filtered out.
  Enablement now follows framework capability, and each framework declares a concept → series map
  in `SPECS`; unmapped concepts are reported as unavailable instead of guessed.

## [v0.6] - 2026-10-04

First public release under the project's canonical repository.
No behavioural change to the console beyond the log-separator fix below.

### Added

- `docs/GLOSSARY.md` — terminology mapping between the Chinese UI and the English codebase.
- Repository-wide version and URL consistency guards
  (`tests/test_repo_consistency.py`).

### Changed

- Version bumped to `v0.6`.
- **All repository URLs** now point at the canonical home
  <https://github.com/stevencui581/WKL-LLM-Ops-Platform>.

### Fixed

- **journalctl boot-separator lines had no timestamp.**
  `journalctl -o short-iso` inserts `-- Boot <id> --` / `-- Reboot --` lines when the queried
  range crosses a reboot. These were returned as ordinary log lines, so the UI rendered a row
  with a blank timestamp, and the acceptance probe (`all(len(ts_local) == 19)`) failed
  **intermittently — only when the host happened to have rebooted inside the queried range**.
  `LogLine` now carries a `kind` field (`log` / `separator`); separators are rendered as a
  divider. Regression tests: `tests/test_log_separator.py`.

## [v0.5.1] - 2026-10-04

Documentation, packaging and one-command installation. No behavioural change to the console itself.

### Added

- **One-command installer** (`install.sh`) — a single copy-paste line that checks the OS and
  dependencies, fetches the source, creates a virtualenv, installs everything, writes `.env`, runs
  a self-check and prints the start command. Bilingual output (auto-detected, overridable with
  `WKL_LANG`).
- **One-command upgrade** (`update.sh`) — backs up state, pulls, updates dependencies,
  self-checks and restarts the service; **rolls back automatically** if any step fails.
- **One-command uninstall** (`uninstall.sh`) — `--purge` removes source, venv and state.
- **Bilingual documentation.** Every document now exists in English (`X.md`) and Chinese
  (`X.zh-CN.md`), following the GitHub convention. Covers README, installation, architecture,
  configuration, API, FAQ, troubleshooting, contributing, security, code of conduct and changelog.
- **Rewritten installation guide** with four explicit sections: operating-system requirements,
  dependency requirements (including every Python package), quick install, and a step-by-step
  manual install where every command is copy-paste ready and every step lists its expected output.
- `AGENTS.md` — project conventions for AI coding agents.
- `.gitattributes` — enforces LF line endings at the git level (see *Fixed*).
- `.python-version`, `VERSION`, `.env.example`.
- `probes/check_install_scripts.sh` — 27-check self-test for the installer scripts
  (syntax, line endings, bilingual help, option parsing).

### Changed

- README reordered to the GitHub convention: `README.md` is English (primary), `README.zh-CN.md`
  is Chinese. The old `README.en.md` is gone.
- Version bumped to `v0.5.1`.
- `deploy/upload.py` now uploads the root-level install scripts so they can be syntax-checked.

### Fixed

- **Guard test bug**: `probes/check_install_scripts.sh` used `\|` inside `grep -E`, where `|` is
  already the alternation operator — the pattern matched a literal backslash-pipe and always
  failed. Caught by running the guard.

## [v0.5] - 2026-10-03

First open-source release. Converted an internal delivery into a general-purpose, deployable project.

### Added

- **Runtime inference-framework detection** (`app/services/framework.py`): identifies llama.cpp,
  Ollama, vLLM, SGLang and OpenAI-compatible servers at startup, together with each one's version
  and available API surface.
  - llama.cpp version comes from `/props` → `build_info` (no need to execute the binary or grep logs)
  - Ollama from `/api/version`, vLLM from `/version`, SGLang from `/get_server_info`
  - Failed detection retries every 30s, covering "console starts before the inference server"
- **Capability gating**: APIs the framework does not provide are no longer probed and no longer
  counted as failures; the UI states "this framework does not expose this API" instead of showing
  a blank panel or a false degraded state.
- **Framework and version in the header**, with both languages supplied by the backend.
- **Open-source compliance guards** (`tests/test_open_source_compliance.py`, 12 checks): LF line
  endings, no credentials in the repo, templated unit files, no private IPs, no developer home paths.
- **Line-ending normaliser** (`tools/fix_line_endings.py`) — repairs CRLF written on Windows
  (CRLF makes Linux shell scripts fail with `set: pipefail: invalid option name`).
- **Externalised deploy parameters** (`deploy/conn.py` + `deploy/host.env.example`): host, user and
  password come from environment variables or an untracked local file. No real credentials in the repo.
- **Templated systemd units**: `__USER__` / `__ROOT__` / `__INFER_UNIT__` are rendered at install
  time, so deploying to any user, directory or inference unit needs no file edits.
- **CI pipeline** (`.github/workflows/ci.yml`): lint, types and tests on Python 3.12, plus a
  line-ending/BOM job, a frontend job and a frontend render smoke test.
- **Complete open-source scaffolding**: README, installation, architecture, configuration, API, FAQ,
  contributing, code of conduct, security policy, issue and PR templates.

### Changed

- Renamed to **WKL-LLM Ops Platform**.
- Version bumped to `v0.5`.
- `pyproject.toml` gained full package metadata (licence, classifiers, keywords, project URLs).
- `upload.py` gained a `--prune` mirror mode so deleted files disappear remotely too.

### Removed

- All deployment-specific facts (hostname, private IP, username, absolute paths, model file names) —
  more than 1,400 occurrences across code, comments, documentation and Word files.
- 29 one-off internal artefacts (reconnaissance scripts, internal doc pipeline, diagnostic scripts).
- Obsolete lint exemptions in `pyproject.toml`.

### Fixed

- `sudo -S` conflicting with a pipe wrote a 0-byte systemd unit file, which systemd reports as
  `masked` — now renders to a temp file and uses `install`.
- Source-scanning guards were fooled by example text inside comments (the same failure mode as the
  v0.4.4 BOM defect) — comments are now stripped before matching.
- A greedy `\S*` in a replacement pattern swallowed quotes and colons, breaking Python syntax.

## [v0.4.4] - 2026-10-03

### Added

- **Defect-regression ledger** (`tests/test_defect_ledger.py`, 30 guards): nine historical defects
  pinned one per guard, each stating the original symptom and criterion.
- **Fix-state auditor** (`probes/audit_defects.py`): independently cross-checks the ledger.
- Preflight loop (`deploy/preflight.py`): upload → remote format + gate → sync back, which
  eliminates local/remote divergence.

### Fixed

- **D9 (newly found)**: `sync_from_host.py` was missing `probes`/`tools`, so fixes made on the
  server never came back and were overwritten by the next upload — presenting as "my change did
  nothing".

## [v0.4.3] - 2026-10-02

### Added

- **Alert log**: 500 entries with paired `raised` / `resolved` records, persisted to disk.
- **Service log history**: 1 / 7 / 30-day ranges, live follow, one-click download.
- **Bilingual UI**: follows the browser language by default, with a remembered manual override.

### Fixed

- **D1 (latent since v0.1)**: the `CLIENT_CANCEL` alert never fired — cancel detection sat after an
  early `return` that triggered because the cancel line has no other parseable fields.
- **D2**: event alerts never resolved — added `event_alert_ttl_s` and timeout-based clearing.
- **D3**: "30 days" only covered one day — the cache key lacked `limit` and the route hard-coded a
  default.
- **D4**: the `spec_types` field was deleted by a careless string replacement.
- **D5**: PowerShell wrote a UTF-8 BOM, breaking source guards and making shell scripts unrunnable.
- **D6**: KV quantisation was labelled "(default)" twice.
- **D7**: the history cache grew without bound (46 MB → 88 MB) — added LRU eviction (max 4 entries).
- **D8**: the document generator inserted zero-width spaces into Chinese text.

## [v0.4] - 2026-10-01

### Added

- **Hardware and software inventory**: CPU, memory, disks, driver, CUDA, cuDNN, NCCL, PyTorch — all
  probed at runtime; absent components show "not installed" rather than a default.
- **Accelerator vendor abstraction**: NVIDIA / AMD / domestic accelerators with a bandwidth table.
- **Automatic baseline learning**: MTP acceptance and decode throughput baselines are learned and
  frozen from real traffic.
- **Service control**: restart / stop / start the inference service with a minimal sudo allowlist.

### Fixed

- Disk capacity was inflated 7× because systemd bind-mounts the same partition — now deduplicated by
  **device**.
- NVLink topology was mis-detected because `\bNV\d*\b` matched the legend text — now only the GPU
  matrix rows are parsed.
- Hardware inventory exceeded its 200 ms budget (246 ms) — made concurrent, now ~125 ms.

## [v0.3.1] - 2026-09-30

### Fixed

- History-log timestamp format and covered-days reporting.
- Static assets not updating due to caching.

## [v0.3] - 2026-09-30

### Added

- Live log WebSocket channel (backfill → incremental).
- Configurable alert thresholds, defined only in `app/config.py`.

## [v0.2] - 2026-09-29

### Added

- Per-slot detail and KV capacity projection.
- GPU temperature, power, VRAM and utilisation collection.
- Prometheus metrics ingestion.

## [v0.1] - 2026-09-28

### Added

- First release: FastAPI backend and static frontend aggregating `nvidia-smi`, `/slots`,
  `/metrics` and `journalctl`.
- Single-worker deployment with systemd integration.
- Versioned-directory release with an atomic symlink and health-gated automatic rollback.

[Unreleased]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.6...HEAD
[v0.6]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.5.1...v0.6
[v0.5.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.5...v0.5.1
[v0.5]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/releases/tag/v0.5
[v0.4.4]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.4.3...v0.4.4
[v0.4.3]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.4...v0.4.3
[v0.4]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.3.1...v0.4
[v0.3.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.3...v0.3.1
[v0.3]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.2...v0.3
[v0.2]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/compare/v0.1...v0.2
[v0.1]: https://github.com/stevencui581/WKL-LLM-Ops-Platform/releases/tag/v0.1
