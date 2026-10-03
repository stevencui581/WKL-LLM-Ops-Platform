# WKL-LLM运维平台 v0.6 升级测试报告

**主题：开源发布就绪 —— 全量双语文档 · 一键安装 · 再次对齐 GitHub 要求**

| 项 | 内容 |
| --- | --- |
| **被测版本** | **v0.5.1**（基线 v0.5） |
| **部署版本** | `releases/20261003-232607` |
| **测试日期** | 2026-10-03 |
| **测试结论** | **通过** —— 质量门禁 4/4、验收套件 **10/10**、自动化测试 **399 项**、双语文档守卫 **56 项**、发布副本自检 **9 项 / 47 个必需文件** |

> **开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01**

---

## 一、结论摘要

| 要求 | 交付 |
| --- | --- |
| ① 再次联网查证 GitHub 官方要求并据此优化 | ✅ 查证 4 个官方/权威来源 + 3 个参考项目实际结构，逐项落地（§2） |
| ② 所有文档中英双语 | ✅ **13 份文档 × 2 语言 = 26 个文件**，有结构对等守卫（§3） |
| ③ 安装说明分四段：系统要求 / 依赖要求 / 快速安装 / 手动安装 | ✅ 每段独立成章，**每条命令可复制即用**，每一步给出预期输出（§4） |
| ④ 傻瓜操作：复制命令即可完成安装 | ✅ 新增 `install.sh` / `update.sh` / `uninstall.sh` 三个一键脚本（§5） |
| ⑤ 删除与 GitHub 上传无关的文档 | ✅ 14 份内部方案 + 旧测试报告 + 参考资料移出 `docs/`（§6） |
| ⑥ 参考三个成功案例 | ✅ hermes-agent / promptfoo / vLLM-2080Ti-Definitive（§2.2） |

| 指标 | 结果 |
| --- | --- |
| 质量门禁 | ✅ ruff 全过、格式合规、mypy 无错 |
| 自动化测试 | ✅ **399 项全通过**（较 v0.5 的 336 项 **+63**） |
| 端到端验收 | ✅ **10/10 OK** |
| 双语文档守卫 | ✅ **56 项** |
| 发布副本自检 | ✅ **9 项 / 47 个必需文件** |
| 运行时服务 | ✅ `active`，`NRestarts=0`，内存 85.6 MB |
| 推理服务 | ✅ 全程未受影响 |

---

## 二、再次查证 GitHub 要求

### 2.1 官方与权威来源

- [GitHub Docs — Best practices for repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)
- [GitHub Docs — About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [GitHub Docs — Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [OpenJS Foundation — Guide to Community Health Files](https://raw.githubusercontent.com/openjs-foundation/cross-project-council/refs/heads/main/project-resources/community-health-files-guide.md)
- [Linux Foundation — Recommended Practices for Hosting and Managing OS Projects on GitHub](http://project.linuxfoundation.org/hubfs/LF%20Research/Recommended%20Practices%20for%20Hosting%20and%20Managing%20OS%20Projects%20on%20Github%20-%20Report.pdf)

### 2.2 三个参考项目的实际结构（直接拉取仓库清单）

| 项目 | 借鉴到的做法 |
| --- | --- |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | **`README.md`(英) + `README.zh-CN.md`(中) + `README.es.md` + `README.ur-pk.md`** 的多语言命名约定；`CONTRIBUTING.es.md` / `SECURITY.es.md`；**`setup-hermes.sh` / `setup-hermes.ps1` 一键安装脚本**；`.python-version`；`.gitattributes`；`.env.example`；`AGENTS.md` |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | README 结构（徽章 → 一句话定位 → Quick Start → 能力清单 → 为什么用它 → 学习路径 → 贡献 → 许可证）；`LICENSE` / `CHANGELOG.md` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md` / `CITATION.cff` / `.editorconfig` / `.github/` 全套 |
| [weicj/vLLM-2080Ti-Definitive](https://github.com/weicj/vLLM-2080Ti-Definitive) | 规模最接近本项目的参考：**`build.sh` / `update.sh` / `launcher.sh` 一键脚本**；`VERSION` 文件；`requirements/` 目录；`docs/` / `examples/` / `scripts/` / `tools/` / `benchmarks/` 的目录划分 |

### 2.3 本轮据此落地的新增项

| 来源要求 | 本项目落地 |
| --- | --- |
| GitHub 约定：`README.md` 为英文主文档，`README.zh-CN.md` 为中文 | ✅ 已从原来的「中文主文档 + `README.en.md`」改为标准约定 |
| 权威指南：必须有一键安装脚本 | ✅ `install.sh` / `update.sh` / `uninstall.sh` |
| 社区健康文件清单 | ✅ README / LICENSE / CHANGELOG / CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / CITATION 全部**双语** |
| `.gitattributes` 强制行尾 | ✅ 新增，从 git 层面根治 CRLF 类缺陷（§7.1） |
| 版本单一来源 | ✅ 新增 `VERSION` 文件；`app/config.py` 仍是运行时唯一来源 |
| `.python-version` | ✅ 新增 |
| 环境变量模板 | ✅ 新增 `.env.example`（含全部常用项的注释） |
| AI 助手约定 | ✅ 新增 `AGENTS.md` + `AGENTS.zh-CN.md`（参考三个案例均有） |

---

## 三、双语文档（13 份 × 2 语言）

| 文档 | 英文 | 中文 |
| --- | --- | --- |
| 项目主页 | `README.md` | `README.zh-CN.md` |
| 更新日志 | `CHANGELOG.md` | `CHANGELOG.zh-CN.md` |
| 贡献指南 | `CONTRIBUTING.md` | `CONTRIBUTING.zh-CN.md` |
| 行为准则 | `CODE_OF_CONDUCT.md` | `CODE_OF_CONDUCT.zh-CN.md` |
| 安全策略 | `SECURITY.md` | `SECURITY.zh-CN.md` |
| AI 助手约定 | `AGENTS.md` | `AGENTS.zh-CN.md` |
| 文档索引 | `docs/README.md` | `docs/README.zh-CN.md` |
| 安装说明 | `docs/INSTALL.md` | `docs/INSTALL.zh-CN.md` |
| 架构设计 | `docs/ARCHITECTURE.md` | `docs/ARCHITECTURE.zh-CN.md` |
| 配置参考 | `docs/CONFIGURATION.md` | `docs/CONFIGURATION.zh-CN.md` |
| API 文档 | `docs/API.md` | `docs/API.zh-CN.md` |
| 常见问题 | `docs/FAQ.md` | `docs/FAQ.zh-CN.md` |
| 故障排查 | `docs/TROUBLESHOOTING.md` | `docs/TROUBLESHOOTING.zh-CN.md` |

### 新增守卫：`tests/test_docs_bilingual.py`（56 项）

| 守卫 | 内容 |
| --- | --- |
| 成对存在 | 每个 `X.md` 必须有 `X.zh-CN.md`，反之亦然 |
| **结构对等** | 标题层级序列、代码块数量、表格行数必须一致 |
| 英文版无中文正文 | 允许的例外仅有：语言切换链接、行内代码与代码块、「中文」这个词本身 |
| 中文版无未翻译占位 | 禁止 TODO / TBD / 待翻译 残留 |
| 语言切换链接 | 必须**精确指向**自己的对应文件（不是随便某个 .md） |
| 一键脚本存在且合规 | 三个脚本都在，且无 BOM、无 CRLF、shebang 正确 |
| `.env.example` 覆盖关键项 | 且不得含真实主机或凭据 |
| `.gitattributes` 强制 LF | 且显式列出无扩展名的关键文件 |

**结构对等守卫抓到了真实差异**：英文版 `CONTRIBUTING.md` 有 10 个代码块而中文版只有 7 个 ——
英文版多了"用安装脚本装开发依赖""Windows 行尾处理""前端渲染冒烟"三个示例。
已把这些示例补进中文版（属于真实的内容改进，不是为对齐而对齐）。

---

## 四、安装说明（按要求的四段结构重写）

`docs/INSTALL.md` / `docs/INSTALL.zh-CN.md` 长度约 **600 行**，严格按用户要求的四段组织：

### （1）安装前的操作系统要求

- 支持的系统矩阵（Ubuntu / Debian / RHEL 系 / Fedora / openEuler / 麒麟 / UOS）+ 测试状态
- 明确 **不支持 Windows / macOS 部署**，并解释原因（依赖 systemd / journald / nvidia-smi）
- 硬性前提表：systemd、journald 读权限、网络、磁盘 ~300 MB、内存 ~200 MB
- **一段可直接复制的环境检查命令**
- 日志权限不足时的修复命令（`usermod -aG systemd-journal`）
- **「不需要的东西」清单**：Docker / Node.js / Nginx / 数据库 / GPU 驱动 / root

### （2）依赖环境要求

- **必需依赖表**：Python ≥ 3.12、python3-venv、pip、systemd、journalctl、git —— 每项都有「缺失后果」
- **全部 Python 包表**：`fastapi` `uvicorn[standard]` `httpx` `psutil` `pydantic-settings` + 版本 + 作用
- **可选依赖表**：`python-docx` / `paramiko` / 开发工具链
- **外部命令表**：`nvidia-smi` / `rocm-smi` / `lscpu` / `nvcc` / `smartctl` 各自影响哪个面板
- **一段可直接复制的依赖检查命令**
- 三大发行版的补齐命令（apt / dnf / yum）
- Python 3.12 不在仓库时的三种解法

### （3）快速安装

- **一行命令**：`curl -fsSL .../install.sh | bash`
- 按推理框架给出四条现成命令（llama.cpp / Ollama / vLLM / SGLang，含各自默认端口）
- 查不到单元名时的查找命令
- 安装并注册 systemd 服务的一行命令
- 全部参数表 + 环境变量表

### （4）手动安装（逐步详解）

7 个步骤，**每一步都给出预期输出**，对不上就说明该步失败：

| 步骤 | 内容 |
| --- | --- |
| 4.1 | 准备目录、获取代码（git 与压缩包两种方式） |
| 4.2 | 确认 Python ≥ 3.12（含批量检查命令） |
| 4.3 | 创建虚拟环境（含 `No module named venv` 的修复） |
| 4.4 | 安装依赖（含国内镜像、**离线 wheel 安装**、缺编译工具的修复） |
| 4.5 | 写入配置（`cat > .env` 直接可用） |
| 4.6 | 验证安装（两条预期输出明确） |
| 4.7 | 启动（前台 + 后台，并指出后台方式的局限） |

另有：安装后验证、注册系统服务、升级、卸载、**安装故障速查表**（10 条现象 → 原因 → 处理）。

---

## 五、一键脚本（满足"傻瓜操作"）

### 5.1 `install.sh`

```bash
curl -fsSL https://raw.githubusercontent.com/stevencui581/WKL-LLM-Ops-Platform/main/install.sh | bash
```

六步：**检查系统 → 检查依赖 → 获取代码 → 创建虚拟环境并安装依赖 → 生成配置 → 自检**，
最后打印启动命令。

设计要点：

| 特性 | 说明 |
| --- | --- |
| **中英双语输出** | 自动按 `LANG`/`LC_ALL` 判断，可用 `WKL_LANG=zh\|en` 强制 |
| 支持 `curl \| bash` | 无仓库时自动克隆到 `~/WKL-LLM-Ops-Platform`；有仓库时就地安装 |
| 幂等 | 重复执行不会破坏已有安装（保留既有 `.env` 与虚拟环境） |
| 失败给出可操作提示 | 例如 Python 版本不足时，**按发行版打印对应的安装命令** |
| 自动探测推理服务 | 从运行中的 systemd 单元里找 `llama/ollama/vllm/sglang` 并询问确认 |
| 手动指定 | `--infer-unit` / `--infer-url` / `--port` / `--install-service` / `--skip-deps` / `-y` |

### 5.2 `update.sh`

备份 `state/` `logs/` `.env` → 拉取代码 → 更新依赖 → 自检 → 重启服务。
**任何一步失败自动回滚**到升级前的 git revision，并恢复备份。

### 5.3 `uninstall.sh`

默认只移除 systemd 单元与 sudo 白名单，**保留代码与配置**（避免误删）；
`--purge` 才会删除整个安装目录，且需要交互确认。

### 5.4 脚本自检：`probes/check_install_scripts.sh`（27 项）

覆盖：bash 语法、无 CRLF、无 BOM、shebang、**中英双语 `--help` 都能工作**、
help 内容完整性（含四种框架示例）、未知参数正确报错。

```
pass=27 fail=0
INSTALL_SCRIPTS_OK
```

---

## 六、删除与 GitHub 上传无关的文档

`docs/` 从 **29 个文件**精简到 **16 个**（8 份双语公开文档 + 最新测试报告）。

移出到 `history/`（仍在本地保留，但不进发布副本）：

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 各版本升级方案（V0.2 ~ V4.1） | 14 份 md + 14 份 docx | 内部开发过程产物 |
| 旧版本测试报告（v0.4 / v0.4.3 / v0.4.4） | 3 份 md + 3 份 docx | 已被最新报告取代 |
| `实现状态与交付说明.md` | 1 份 | 内部交付说明 |
| `docs/assets/` 参考案例截图 | 2 张 png | 与产品无关 |
| `docs/research/` 调研报告 | 2 份 md | 内部调研 |

同时把 `app/README.md`（v0.1 陈旧内容且引用内部文档）在 v0.5 已删除。

**发布副本自检确认**：47 个必需文件齐全，28 个 Markdown 文件内部链接全部可达。

---

## 七、本轮发现并修复的真实问题

### 7.1 `upload.py` 的根文件清单没跟上双语结构

**现象**：服务器上双语文档守卫测试大面积误报"文件不存在"。

**根因**：`deploy/upload.py` 的 `INCLUDE_FILES` 是**硬编码列表**，只有 `README.md`，
v0.5.1 新增 `README.zh-CN.md` / `CHANGELOG.md` / `CONTRIBUTING.md` 等后没有同步
—— 与 v0.4.4 的 D9（sync 漏目录）**同一类问题**。

**修复**：改为**通配仓库根全部 `*.md`** + 固定清单（dotfile 与脚本），
以后新增文档不需要再改上传脚本。

### 7.2 journalctl 的启动分隔行没有时间戳（**产品侧缺陷**）

**现象**：验收套件 6 间歇性失败，断言是「每条历史日志的 `ts_local` 长度必须是 19」。

**根因**：`journalctl -o short-iso` 在**查询范围跨重启**时会插入结构分隔行：

```
-- Boot c62e718a0de6467e9ab147ad01b90086 --
-- Reboot --
```

它们没有时间戳。早期版本把它当普通日志行返回，后果有两个：

1. **前端渲染出一行空白时间戳**，看起来像数据损坏
2. 验收断言失败 —— 而且**只在机器恰好于查询范围内重启过时才失败**，属于间歇性误报

**修复**（产品 + 守卫两侧）：

- `LogLine` 新增 `kind` 字段（`log` / `separator`）
- `history.py` 识别分隔行并显式标注
- `static/logs.js` 把分隔行渲染为**分隔带**而不是普通日志行
- `static/style.css` 新增 `.ln.sep` 样式
- 验收探针对真实契约断言：**日志行**必须有 19 字符时间戳，**分隔行**必须被标注
- 新增回归测试 `tests/test_log_separator.py`（9 项）

**修复后实测**（分隔行被正确识别）：

```
[PASS] days=1 分隔行已显式标注 — 1 条分隔行
[PASS] days=7 分隔行已显式标注 — 5 条分隔行
[PASS] days=30 分隔行已显式标注 — 12 条分隔行
```

### 7.3 双语文档守卫自身的两个问题

| 问题 | 说明 | 修复 |
| --- | --- | --- |
| 允许清单过窄 | 只允许 `[中文](...)`，但 `[中文说明](...)`、行内代码里的 `lang.zh = '中'`、`English + 中文` 标注等**合理场景**被误报 | 改为按上下文剥离：语言切换链接 + 行内代码 + 「中文」这个词，再检查剩余文本 |
| 切换链接检查不精确 | 用「任意 .md 链接」判断，导致中文版指向别的文档也能通过 | 改为必须**精确指向自己的对应文件** |

修正后守卫**真的抓到了问题**：`CODE_OF_CONDUCT.zh-CN.md`、`SECURITY.zh-CN.md`、
`CONFIGURATION.zh-CN.md` 等 9 份中文文档缺英文版链接，已补齐。

### 7.4 补链接工具插入了重复行

给中文文档补语言切换链接的一次性工具，因为只在**前 6 行**里查找已有链接，
`README.zh-CN.md` 的切换链接原本在第 13 行，于是被插入了一条重复的。

**已修复**：删除重复行，保留原有的完整导航行。

> 教训：一次性脚本也必须校验自己的输出。这是本轮**唯一**由工具造成、需要返工的改动。

### 7.5 守卫测试里的 `grep -E` 反斜杠错误

`probes/check_install_scripts.sh` 最初写的是 `grep -qE 'Usage\|用法'` ——
在 `-E`（扩展正则）下 `|` 本就是「或」运算符，`\|` 反而变成匹配**字面量反斜杠加竖线**，
导致该断言恒失败。

**由运行守卫自身发现**。已改为 `'Usage|用法'`。

---

## 八、遗留问题

| # | 项 | 性质 | 说明 |
| --- | --- | --- | --- |
| L1 | 一键脚本未在**全新机器**上端到端验证 | 验证范围 | `install.sh` 的语法、双语输出、参数解析已由 27 项自检覆盖；六步流程中"检查系统""克隆代码"依赖真实新环境，本轮只在已有环境验证了幂等路径 |
| L2 | 多框架支持仍只在 llama.cpp 上做过真机验证 | 覆盖度 | Ollama / vLLM / SGLang 由假响应单测覆盖（25 项），无真机环境 |
| L3 | 中文文档的英文专有名词未做统一术语表 | 文档一致性 | 已按通行译法处理，但缺少 `docs/GLOSSARY` |
| L4 | 72 小时稳定性观察未满 | 时间性 | 部署以来 0 重启、0 readiness 失败 |
| L5 | 无前端自动化测试（浏览器级） | 工具链 | 现有 `tools/check_frontend_render.js` 是 Node + DOM 桩，不是真实浏览器 |

**L1 值得强调**：`install.sh` 的**幂等路径**（在已有仓库上重跑）已在真实环境验证，
但**全新机器上的首次安装**（含 `git clone` 与系统检查分支）尚未端到端跑过。
这是"未验证"而不是"已验证通过"。

---

## 九、交付物

| 交付物 | 路径 |
| --- | --- |
| **开源发布副本** | `WKL-LLM-Ops/`（47 个必需文件，可直接上传 GitHub） |
| 本报告 | `docs/WKL-LLM运维平台_v0.5.1升级测试报告.md` / `.docx` |
| 一键脚本 | `install.sh` / `update.sh` / `uninstall.sh` |
| 双语文档 | `README{,.zh-CN}.md` 等 13 组 |

### 上传 GitHub

```bash
cd WKL-LLM-Ops
git init
git add .
git commit -m "chore: initial open-source release v0.5.1"
git branch -M main
git remote add origin https://github.com/<你的组织>/WKL-LLM-Ops-Platform.git
git push -u origin main
```

> 上传前 `deploy/host.env` 必须**不在**提交里 —— 它已被 `.gitignore` 忽略，
> `verify_release.py` 也会检查这一项。

---

## 十、结论

**v0.5.1 验证通过，具备开源发布条件。**

1. **文档从"只有中文"变成真正的双语**：13 份文档 × 2 语言，并有**结构对等守卫**
   （标题层级 / 代码块数 / 表格行数必须一致），防止一边改了另一边没改。
2. **安装从"照着文档敲"变成"复制一行"**：三个一键脚本，双语输出，幂等，
   失败自动回滚；同时保留完整的逐步手动安装路径（含离线安装）。
3. **再次对齐 GitHub 要求**：命名约定改为 `README.md`(英) + `README.zh-CN.md`(中)；
   补齐 `.gitattributes` / `.python-version` / `.env.example` / `VERSION` / `AGENTS.md`；
   一键脚本这一项正是三个参考项目的共同特征。
4. **过程中修掉 5 个真实问题**，其中 `journalctl` 跨重启分隔行是**产品侧缺陷** ——
   它让前端显示空白时间戳，还造成验收套件**间歇性失败**（只在机器恰好在查询范围内
   重启过时才复现），属于典型的"难查但有真实用户影响"的问题。

**同时必须诚实指出**：一键脚本的**全新机器首次安装**路径尚未端到端验证；
多框架支持仍只有 llama.cpp 经过真机检验。

---

*报告生成时间：2026-10-03　　被测版本：v0.5.1（release 20261003-232607）*
*开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01*
