# Glossary · 术语对照表

[中文](#中文--english) · [English](#english--中文) · [Project home](../README.md)

This file is intentionally **bilingual in one table**: it maps the Chinese wording used in the UI
and comments to the English wording used in code, docs and issues. When a term needs to change,
change it here first and then follow the mapping everywhere else.

本文档刻意做成**单文件双语**：它把界面与注释里的中文说法，与代码、文档、Issue 里的英文说法对应
起来。术语要改时，先改这里，再按对照关系改其它地方。

## 中文 → English

| 中文（界面/注释） | English（代码/文档） | 说明 |
| --- | --- | --- |
| 算力卡 | accelerator / GPU | 泛指 GPU；具体型号一律运行期探测 |
| 槽位 | slot | llama.cpp 的 `/slots` 概念 |
| KV 容量 | KV capacity | 上下文缓存容量 |
| KV 余量 | KV headroom | 还够多少 token |
| 容量模式 | capacity mode | `unified`（统一池）/ `per_slot`（每槽独立） |
| prompt cache | prompt cache | 不译；指槽位空闲时保留的前缀缓存 |
| 推理框架 | inference framework | llama.cpp / Ollama / vLLM / SGLang 等 |
| 被监控单元 | monitored unit | systemd 单元名 |
| 服务运行时长 | service uptime | 顶栏「服务运行」 |
| 硬件清点 | hardware inventory | CPU / 内存 / 磁盘 / 驱动 / 库版本 |
| 降级 | degraded | 采集失败导致的状态 |
| 陈旧 | stale | 连续多次采集失败 |
| 告警 | alert | 含阈值告警与事件告警 |
| 告警日志 | alert log | 含 raised / resolved 成对记录 |
| 阈值告警 | threshold alert | 与基线比较得出 |
| 事件告警 | event alert | 由日志事件触发，超时自动恢复 |
| 自动恢复 | auto-resolve | 事件告警超出 TTL 后自动标记 resolved |
| 基线 | baseline | 自动学习，**不得写死** |
| 阈值 | threshold | 只允许定义在 `app/config.py` |
| 防抖 | sustain window | 持续超过该时长才告警 |
| 历史服务日志 | service log history | 1 / 7 / 30 天档位 |
| 实时日志 | live log | WebSocket 增量推送 |
| 回填 | backfill | 连接建立时先发的历史行 |
| 服务管理 | service control | 重启 / 停止 / 启动推理服务 |
| 探针 | probe | `probes/` 下的线上验收脚本 |
| 守卫 | guard | `tests/` 下防止回归的测试 |
| 台账 | ledger | 缺陷回归清单 |
| 发布副本 | release copy | 用于上传 GitHub 的干净目录 |
| 部署根目录 | install root | 仓库解压后的位置 |
| 一键脚本 | one-command script | `install.sh` / `update.sh` / `uninstall.sh` |

## English → 中文

| English | 中文 | Notes |
| --- | --- | --- |
| accelerator | 算力卡 | umbrella term; the exact model is always probed |
| slot | 槽位 | the llama.cpp `/slots` concept |
| KV capacity | KV 容量 | context cache capacity |
| KV headroom | KV 余量 | how many tokens are still available |
| capacity mode | 容量模式 | `unified` / `per_slot` |
| prompt cache | prompt cache | not translated |
| inference framework | 推理框架 | llama.cpp / Ollama / vLLM / SGLang … |
| monitored unit | 被监控单元 | a systemd unit name |
| service uptime | 服务运行时长 | header chip |
| hardware inventory | 硬件清点 | CPU / memory / disks / driver / library versions |
| degraded | 降级 | a collection failure |
| stale | 陈旧 | several consecutive collection failures |
| alert | 告警 | threshold and event alerts |
| alert log | 告警日志 | paired raised / resolved records |
| threshold alert | 阈值告警 | derived from a baseline comparison |
| event alert | 事件告警 | triggered by a log event; auto-resolves on a TTL |
| auto-resolve | 自动恢复 | marks an event alert resolved after its TTL |
| baseline | 基线 | auto-learned; **never hard-code it** |
| threshold | 阈值 | may only be defined in `app/config.py` |
| sustain window | 防抖 | must persist this long before alerting |
| service log history | 历史服务日志 | 1 / 7 / 30-day ranges |
| live log | 实时日志 | incremental WebSocket stream |
| backfill | 回填 | history sent when a connection opens |
| service control | 服务管理 | restart / stop / start the inference service |
| probe | 探针 | live acceptance scripts under `probes/` |
| guard | 守卫 | regression tests under `tests/` |
| ledger | 台账 | the defect regression list |
| release copy | 发布副本 | the clean tree uploaded to GitHub |
| install root | 部署根目录 | where the repository is unpacked |
| one-command script | 一键脚本 | `install.sh` / `update.sh` / `uninstall.sh` |

## Naming conventions · 命名约定

| Rule | 约定 |
| --- | --- |
| Repository name | `WKL-LLM-Ops-Platform` |
| Python distribution name | `wkl-llm-ops` (independent of the repository name) |
| Product display name | `WKL-LLM运维平台` / `WKL-LLM Ops Platform` |
| Version display | `v0.6` (product) · `0.6.0` (package) |
| Chinese docs | `X.zh-CN.md` |
| English docs | `X.md` |
| Category label | 算力卡 → **Compute card** in UI strings; `accelerator` in code identifiers |

> The one place where UI wording and code wording deliberately differ is 算力卡:
> the user-facing label is **Compute card** / **算力卡**, while code identifiers and docs use
> `accelerator`. That is intentional — keep it that way.
