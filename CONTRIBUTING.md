# Contributing

Thanks for wanting to contribute to WKL-LLM Ops Platform. This document covers how to set up a
development environment, the conventions the project follows, and how to get a pull request merged.

[中文](CONTRIBUTING.zh-CN.md) · **English**

## Contents

- [Code of Conduct](#code-of-conduct)
- [Development setup](#development-setup)
- [Before you submit](#before-you-submit)
- [Code conventions](#code-conventions)
- [Project-specific hard constraints](#project-specific-hard-constraints)
- [Commit messages](#commit-messages)
- [Pull request flow](#pull-request-flow)
- [Reporting a bug](#reporting-a-bug)

## Code of Conduct

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

**Python 3.12+** is required, on **Linux**. This project targets Linux only: Windows and macOS are
neither supported for deployment nor for development. A few tests and `mypy` rely on Linux-only
facilities (`socket.AF_UNIX`, `/proc`), so the quality gate does not pass elsewhere.

```bash
git clone https://github.com/stevencui581/WKL-LLM-Ops-Platform.git
cd WKL-LLM-Ops-Platform

python3 -m venv venv
./venv/bin/pip install -e '.[dev]'

# Optional: doc export and remote-deploy helpers
./venv/bin/pip install -e '.[docs,remote]'
```

Or use the installer, then add the dev extras:

```bash
bash install.sh --skip-deps
./venv/bin/pip install -e '.[dev]'
```

Run the console:

```bash
export LLMCONSOLE_LLAMA_UNIT=llama-server.service
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8081 --workers 1
```

> **`--workers 1` is mandatory.** The process owns a journalctl follower, a WebSocket connection
> set and hardware caches; multiple workers split that state.

## Before you submit

```bash
bash selfcheck.sh
```

It runs, in order:

| Step | Command | Purpose |
| --- | --- | --- |
| 1/4 | `ruff check app tests deploy probes tools` | Lint (includes the `ASYNC` ruleset) |
| 2/4 | `ruff format --check` | Formatting |
| 3/4 | `mypy app` | Type checking |
| 4/4 | `pytest` | Unit tests |

To fix formatting:

```bash
./venv/bin/ruff check --fix app tests deploy probes tools
./venv/bin/ruff format app tests deploy probes tools
```

If any file was written on a non-Linux machine (for example a Windows editor), also run:

```bash
python tools/fix_line_endings.py
python tools/strip_bom.py
```

Windows editors write CRLF by default, and CRLF makes Linux shell scripts fail with
`set: pipefail: invalid option name`. CI enforces this.

If a service is running you can also run the full acceptance suite:

```bash
bash deploy/verify_all.sh        # 10 suites
```

And the frontend render smoke test (needs Node):

```bash
node tools/check_frontend_render.js static
```

## Code conventions

- **Comments and docstrings are written in Chinese** (this is a Chinese-first operations project);
  identifiers are English. Comments explain *why*, not *what*.
- **The `ASYNC` ruff ruleset must stay enabled.** It statically catches `subprocess.run`,
  `time.sleep` and friends inside `async def` — invisible at runtime and very hard to debug.
- **Thresholds and constants go in `app/config.py`.** Do not scatter magic numbers through
  collectors.
- **Never hard-code user-facing text in JavaScript.** All strings live in `static/i18n.js`
  (`DICT.zh` / `DICT.en`) and are read through `t(key)`. Backend payloads ship structured,
  language-neutral fields.
- **Put new tests in `tests/`** as pure-function tests; anything that needs a live service belongs
  in `probes/`.

## Project-specific hard constraints

These were all learned from real incidents. A PR that violates one will be asked to change.

1. **No hardware or deployment facts in production code.**
   No model names, driver versions, absolute paths, model file names or hostnames. Probe everything
   at runtime. A failed probe shows *unknown*; a missing component shows *not installed*;
   **never substitute a default**.
   Guards: `tests/test_no_hardcoded_deployment.py`, `tests/test_open_source_compliance.py`.

2. **No new image assets.** The frontend stays image-free (no `<img>`, no `background-image`,
   no external `url(...)`). Guard: `deploy/check_frontend.py`.

3. **No CJK in the English dictionary.** `DICT.en` must contain no CJK characters (the single
   exception is the language-switch button's `lang.zh = '中'`). Guard: `tests/test_i18n.py`.

4. **Source-scanning guards must strip comments first.** An example inside a comment causes both
   false positives and false negatives. See `_strip_py()` / `_code()` in
   `tests/test_defect_ledger.py`.

5. **Never pipe content into `sudo -S`.** It reads the password from stdin, so piped content is
   consumed by the prompt and the target file ends up 0 bytes — systemd then reports the unit as
   `masked`. Render to a temp file, then `install`/`cp`.
   Guard: `tests/test_open_source_compliance.py`.

6. **Everything the frontend reads must be in the snapshot.** `WS /ws/metrics` overwrites the page
   every 2 seconds, so a field present only on a REST route silently disappears. Guards:
   `tests/test_snapshot_fields.py`, `probes/e2e_ws_snapshot.py`.

7. **One source of truth for the version.** `app/config.py`. No version literals in the frontend.
   Guard: `tests/test_v043_features.py`.

8. **LF line endings only.** Enforced by `.gitattributes` and checked in CI.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<optional body: why this change is needed>
```

| type | Use for |
| --- | --- |
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Refactor with no behaviour change |
| `test` | Tests |
| `chore` | Build / tooling |

Example:

```
feat(framework): detect SGLang version from /get_server_info

SGLang reports its version on /get_server_info rather than /version,
so it was detected as "framework known, version unknown".
```

## Pull request flow

1. Fork the repo and branch from `main`: `git checkout -b fix/kv-eviction`.
2. Make the change, **and add the guard test** — a bug fix must ship a regression test.
3. Run `bash selfcheck.sh` until it is green.
4. Open the PR and complete the checklist in the template.
5. A maintainer will review; a green CI run is required before merge.

## Reporting a bug

- Use the [issue templates](https://github.com/stevencui581/WKL-LLM-Ops-Platform/issues/new/choose).
- Include the **framework and version** (visible in the header, hover for details), your OS,
  your Python version, and the relevant lines from
  `journalctl -u llm-console.service`.
- **Do not open a public issue for a security vulnerability** — follow the
  [Security Policy](SECURITY.md).
