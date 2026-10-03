# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, Copilot, Codex, DSH, …) working in this
repository. Humans should read [CONTRIBUTING.md](CONTRIBUTING.md) instead.

[中文说明](AGENTS.zh-CN.md) · **English**

---

## Project in one paragraph

**WKL-LLM Ops Platform** is a lightweight operations console for a **locally hosted** LLM
inference server (llama.cpp / Ollama / vLLM / SGLang). Python 3.12 + FastAPI backend, plain-JS
frontend with **no build step**, deployed as a **single process** on Linux with systemd. Every
hardware, driver and framework fact is **probed at runtime** — nothing is hard-coded.

## Commands you will need

```bash
# Quality gate — run this before proposing any change
bash selfcheck.sh                    # ruff check + ruff format --check + mypy + pytest

# Fix formatting
./venv/bin/ruff check --fix app tests deploy probes tools
./venv/bin/ruff format app tests deploy probes tools

# Single test file
./venv/bin/python -m pytest tests/test_framework.py -q

# Live acceptance (needs a running service)
bash deploy/verify_all.sh            # 10 suites

# Frontend render smoke test (needs Node)
node tools/check_frontend_render.js static

# Line endings + BOM (run after editing files on Windows)
python tools/fix_line_endings.py
python tools/strip_bom.py
```

**There is no frontend build step.** Edit `static/*.js|html|css` and reload the browser.

## Non-negotiable constraints

These are enforced by tests. Violating them will fail CI.

### 1. No hardware or deployment facts in production code

Never write a GPU model, driver version, absolute path, model file name or hostname into
`app/`, `static/`, `deploy/` or `probes/`.

| Situation | Required display |
| --- | --- |
| Probe succeeded | the actual value |
| Probe failed | `unknown` |
| Component absent | `not installed` |

**Never substitute a default.** Guards: `tests/test_no_hardcoded_deployment.py`,
`tests/test_open_source_compliance.py`.

### 2. No image assets in the frontend

No `<img>`, no `background-image`, no external `url(...)`. Icons are CSS/Unicode.
Guard: `deploy/check_frontend.py`.

### 3. Bilingual UI, language-neutral backend

User-facing text lives in `static/i18n.js` (`DICT.zh` / `DICT.en`) and is read through `t(key)`.
Backend payloads ship **structured, language-neutral fields** (codes, or `{zh, en}` pairs).
`DICT.en` must contain **no CJK**. Guard: `tests/test_i18n.py`.

### 4. `I18N.lang` must stay a getter

`static/i18n.js` exports `lang` via `Object.defineProperty`. Writing `lang: LANG` snapshots the
value at load time, so a language switch would leave other modules reading the old language.
Guard: `tests/test_snapshot_fields.py`.

### 5. Everything the frontend reads must be in the snapshot

`MetricSnapshot` (`app/models.py`) is what `WS /ws/metrics` broadcasts. The page is
**overwritten every 2 seconds**, so a field that exists only on the REST route disappears.

This caused a real bug: the header framework chip showed "detecting…" forever because
`framework` was only added in `overview.py`. Guards:
`tests/test_snapshot_fields.py`, `probes/e2e_ws_snapshot.py`.

### 6. Strip comments before scanning source

Source-scanning guards must call `_strip_py()` / `_code()` (see `tests/test_defect_ledger.py`)
first. A comment containing an example produces both false positives and false negatives.

### 7. Never pipe content into `sudo -S`

`sudo -S` reads the password from **stdin**, so piped content is consumed by the prompt and the
target file is written as 0 bytes — systemd then reports the unit as `masked`. Render to a temp
file, then `install`/`cp`.

Guard: `tests/test_open_source_compliance.py::test_install_scripts_render_but_do_not_pipe_to_sudo`

### 8. LF line endings only

CRLF breaks shell scripts (`set: pipefail: invalid option name`), extension-less config files
(sudoers) and CSV fixtures. `.gitattributes` enforces LF; `tools/fix_line_endings.py` repairs.
Guard: `tests/test_open_source_compliance.py::test_no_crlf_line_endings`

### 9. One source of truth for the version

`app/config.py` (`product_version`, `product_name`). No version literals in the frontend.
Guard: `tests/test_v043_features.py::test_page_scripts_have_no_version_literal`

### 10. Single Uvicorn worker

`--workers 1` is mandatory: the process owns a journalctl follower, a WebSocket connection set
and hardware caches. Never suggest raising it.

## Architecture orientation

| Path | Responsibility |
| --- | --- |
| `app/services/framework.py` | ★ Runtime framework detection. **Data-table driven** (`SPECS`) — add a framework by adding a row, not an `if` |
| `app/services/aggregator.py` | Concurrent collection, capability gating, snapshot construction |
| `app/services/alerts.py` | Threshold + event alerts, including **automatic resolution** |
| `app/services/baseline.py` | Auto-learned MTP / decode baselines (never hard-code these) |
| `app/collectors/` | One collector per data source; each has a pure-function parser with unit tests |
| `app/routes/` | REST endpoints |
| `app/main.py` | Lifespan, framework detection, tick loop, WebSocket routes |
| `static/app.js` | Main page rendering. All text via `t()` |
| `deploy/` | Deploy, rollback, acceptance scripts (unit file is a **template**) |
| `probes/` | Live acceptance and diagnostics (run against a real service) |

## How to add a new inference framework

1. Add a `FrameworkSpec` entry to `SPECS` in `app/services/framework.py`:
   detection paths, version source, capability set, metrics prefix, bilingual notes.
2. Add a fake-response test in `tests/test_framework.py` following the existing pattern.
3. If it needs a new capability, add the constant near the other `CAP_*` names and gate the
   relevant collector through `aggregator.set_framework()`.

Do **not** add `if framework == "x"` anywhere in `app/collectors/` — the guard
`test_no_hardcoded_framework_in_collectors` will fail.

## Testing expectations

- Every behaviour change needs a test.
- Every **bug fix** needs a regression test that states the original wrong criterion.
- Pure logic (parsers, formula, state machines) → `tests/`.
- Anything needing a live service → `probes/`.
- Frontend rendering → `tools/check_frontend_render.js` (Node harness with browser stubs).

## When you are done

```bash
bash selfcheck.sh
```

Must be green. If you edited files on Windows, run `python tools/fix_line_endings.py` first.
