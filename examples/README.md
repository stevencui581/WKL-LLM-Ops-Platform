# Examples · 配置档案

**单文件双语** · Single-file bilingual · [Project home](../README.md) · [Installation](../docs/INSTALL.md)

Ready-to-use configuration profiles, one per inference framework. Each file is a complete `.env`
you can copy and start from.

按推理框架分好的现成配置档案。每个文件都是一份完整的 `.env`，复制过去就能用。

## Available profiles · 可用档案

| File | Framework | Default port | Per-slot panel |
| --- | --- | ---: | --- |
| [`llama-cpp.env`](llama-cpp.env) | llama.cpp (`llama-server`) | 8080 | ✅ available |
| [`ollama.env`](ollama.env) | Ollama | **11434** | ❌ not exposed |
| [`vllm.env`](vllm.env) | vLLM | **8000** | ❌ not exposed |
| [`sglang.env`](sglang.env) | SGLang | **30000** | ❌ not exposed |

> **The port is the most common mistake.** Only llama.cpp uses 8080. If the console shows "not
> identified", check the port first.
>
> **端口是最常见的错误。** 只有 llama.cpp 用 8080。如果控制台显示「未识别」，先查端口。

## How to use · 怎么用

1. Find the real systemd unit name on your host:

   ```bash
   systemctl list-units --type=service --state=running | grep -Ei 'llama|ollama|vllm|sglang'
   ```

2. Copy the matching profile and edit `LLMCONSOLE_LLAMA_UNIT` to that name:

   ```bash
   cp examples/llama-cpp.env .env
   ```

3. Verify the console can be reached at that address:

   ```bash
   ./venv/bin/python probes/diag_framework_chip.py
   ```

4. Start the console:

   ```bash
   ./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --workers 1
   ```

## Rules that apply to every profile · 所有档案共同的规则

| Rule · 规则 | Why · 原因 |
| --- | --- |
| Never hard-code `MTP_ACCEPT_BASELINE` / `DECODE_BASELINE_TPS` | Baselines are auto-learned per machine. A stale one causes permanent false alerts. |
| 绝不手填基线 | 基线按机器自动学习；写死的基线会导致长期误报。 |
| Keep `event_alert_ttl_s` non-zero | Event alerts must auto-resolve, or the UI hangs on a resolved event forever. |
| 保持 `event_alert_ttl_s` 非零 | 事件告警必须能自动恢复，否则界面会永久挂着已结束的事件。 |
| Raise `poll_interval_s` rather than lowering it | Collection competes with the inference server for CPU. |
| 要调就调大 `poll_interval_s`，不要调小 | 采集会与推理服务争抢 CPU。 |
| Set `--workers 1` always | The process owns the journalctl follower, WebSocket set and hardware caches. |
| 始终 `--workers 1` | 进程内持有 journalctl 跟随器、WebSocket 连接集合与硬件缓存。 |

## Full reference · 完整参数

Every setting, with the trade-off behind it: [`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md)
（[中文](../docs/CONFIGURATION.zh-CN.md)）
