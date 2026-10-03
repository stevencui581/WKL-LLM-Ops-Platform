# Documentation

**English** · [中文](README.zh-CN.md) · [Project home](../README.md)

## Getting started

| Document | Contents |
| --- | --- |
| [Installation](INSTALL.md) | OS requirements, dependencies, quick install, step-by-step manual install, verification, upgrade, uninstall |
| [Configuration](CONFIGURATION.md) | Every setting and the trade-off behind it |
| [FAQ](FAQ.md) | Framework detection, data accuracy, security trade-offs, development |
| [Troubleshooting](TROUBLESHOOTING.md) | Symptom-driven playbook |

## For developers

| Document | Contents |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Data flow, core modules, design principles, deployment model |
| [API](API.md) | REST and WebSocket endpoints, payloads, examples |
| [Contributing](../CONTRIBUTING.md) | Dev setup, conventions, hard constraints, PR flow |
| [Security policy](../SECURITY.md) | Reporting, deployment hardening, accepted trade-offs |
| [Changelog](../CHANGELOG.md) | Release history |
| [AGENTS.md](../AGENTS.md) | Guidance for AI coding agents |

## Quick navigation

- **Just got the project** → [Installation](INSTALL.md)
- **Running, but the page is empty** → [Troubleshooting](TROUBLESHOOTING.md)
- **Header says "not identified"** → [FAQ](FAQ.md)
- **Want to change alert thresholds** → [Configuration](CONFIGURATION.md)
- **Want to support a new framework** → [FAQ](FAQ.md) and [Architecture](ARCHITECTURE.md)
- **Want to contribute** → [Contributing](../CONTRIBUTING.md)

## Two principles worth reading first

Whether you are deploying or extending the project, these are the two easiest things to get wrong.

### 1. Every hardware fact is probed at runtime

Production code must **never** contain a model name, driver version, absolute path, model file
name or hostname. A failed probe shows *unknown*; a missing component shows *not installed*.
**Never substitute a default.**

That is what makes the project portable across machines, frameworks and hardware without code
changes.

### 2. An unsupported API must be "not collected", not "collection failed"

If the console probes an endpoint the current framework does not provide, it produces a flood of
stale alerts that look like the console is broken — when in fact the framework simply differs.

The console gates capabilities on the detected framework and explains the difference in the UI.
See [Architecture](ARCHITECTURE.md).
