# WKL-LLM运维平台 v0.6 升级测试报告

**主题：正式发布 —— 版本号统一 · 仓库地址统一 · 排版对齐成功案例 · 已上传 GitHub 并通过 CI**

| 项 | 内容 |
| --- | --- |
| **被测版本** | **v0.6**（基线 v0.5.1） |
| **部署版本** | `releases/20261004-001900` |
| **正式仓库** | <https://github.com/stevencui581/WKL-LLM-Ops-Platform> |
| **测试日期** | 2026-10-04 |
| **测试结论** | **通过** —— 质量门禁 4/4、验收套件 **10/10**、自动化测试 **425 项**、仓库一致性守卫 **26 项**、双语文档守卫 **56 项**、发布副本自检 **9 项 / 52 个必需文件** |

> **开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01**

---

## 一、结论摘要

| 步骤 | 任务 | 结果 |
| --- | --- | --- |
| 1 | 升级到 v0.6，统一全项目版本号 | ✅ 代码 / 文档 / 脚本全部统一；新增版本一致性守卫 |
| 2 | 统一 GitHub 地址为正式仓库 | ✅ **76 处**替换；含克隆目录名同步；新增地址一致性守卫 |
| 3 | 上传到 GitHub + 按成功案例优化排版 | ✅ **已上传** —— 183 个文件，<https://github.com/stevencui581/WKL-LLM-Ops-Platform> |

| 指标 | 结果 |
| --- | --- |
| 质量门禁 | ✅ ruff 全过、89 文件格式合规、mypy 40 文件无错 |
| 自动化测试 | ✅ **425 项全通过**（较 v0.5.1 的 399 项 **+26**） |
| 端到端验收 | ✅ **10/10 OK** |
| 仓库一致性守卫 | ✅ **26 项**（版本号 5 组 + 地址 10 组 + 目录名 + 第三方保护） |
| 发布副本自检 | ✅ **9 项 / 52 个必需文件** |
| 本地 git 仓库 | ✅ 8 个提交，183 个文件，分支 `main` |
| **GitHub 上传** | ✅ **182 个文件已上线**，`REMOTE_VERIFY_OK`，本地与远程 HEAD 一致 |
| **GitHub CI** | ✅ **6/6 job 全绿**（首次推送时为红，见 §6.6~6.8） |
| 运行时服务 | ✅ `active`，`NRestarts=0` |
| 推理服务 | ✅ 全程未受影响 |

---

## 二、第 1 步：版本号统一到 v0.6

### 2.1 关键设计决策：区分「当前版本」与「历史标注」

项目里的版本号有**两类**，含义完全不同：

| 类别 | 例子 | 处理 |
| --- | --- | --- |
| **当前版本** | `product_version`、页面占位、徽章、pyproject、VERSION、测试断言、文档预期输出 | **必须升级** |
| **历史标注** | 「（v0.5 新增）」「v0.4.3 踩过的坑」「v0.5 §1」、更新日志旧条目 | **必须保留原文** |

> 改掉历史标注，就等于声称"这个功能是 v0.6 才加的" —— 那是在**篡改开发记录**。

第一版工具用宽松正则演练，**56 个文件里有大半是历史注释被误改**，因此改为**精确到上下文的规则表**
（`tools/bump_version.py`），只列 17 条规则，改完再把剩余命中逐条列出来人工判定。

### 2.2 实际改动

**17 个文件**（精确规则），外加 3 处手工修正：

| 位置 | 旧 | 新 |
| --- | --- | --- |
| `app/config.py` `product_version` | `v0.5.1` | **`v0.6`** |
| `app/config.py` `product_name` | `WKL-LLM运维平台v0.5.1` | **`WKL-LLM运维平台v0.6`** |
| `app/config.py` `product_name_spaced` | `WKL-LLM运维平台 v0.5.1` | **`WKL-LLM运维平台 v0.6`** |
| `pyproject.toml` | `0.5.0` | **`0.6.0`** |
| `VERSION` | `0.5.1` | **`0.6.0`** |
| `CITATION.cff` | `0.5` | **`0.6.0`** |
| 三个页面 `.ver` 占位 | `v0.5.1` | **`v0.6`** |
| README 徽章（中英） | `version-v0.5.1` | **`version-v0.6`** |
| README 底部署名（中英） | `v0.5.1` | **`v0.6`** |
| 测试断言 3 处 | `"v0.5.1"` | **`"v0.6"`** |
| `docs/INSTALL{,.zh-CN}.md` 预期输出 | `WKL-LLM运维平台v0.5.1 v0.5.1` | **`WKL-LLM运维平台v0.6 v0.6`** |
| `SECURITY{,.zh-CN}.md` 支持版本表 | `v0.5.x` / `< v0.5` | **`v0.6.x`** / **`< v0.6`** |
| `deploy/verify_all.sh` 套件标题 | `（v0.4 + v0.4.3 + v0.5）` | **`（v0.4 ~ v0.6）`** |

**变更日志**新增 `## [v0.6]` 段（中英两份），并更新底部链接定义。

### 2.3 新增守卫 `tests/test_repo_consistency.py`（26 项）

| 守卫 | 内容 |
| --- | --- |
| 版本唯一来源 | `app/config.py` 的三个字段必须是当前版本 |
| 包版本一致 | `pyproject.toml` / `VERSION` / `CITATION.cff` 必须等于 `0.6.0` |
| 页面占位一致 | 三个页面都必须是 `v0.6` |
| 徽章一致 | 两个 README 的徽章版本 |
| **前端脚本无版本字面量** | 防止再出现 `\|\| 'v0.4.3'` 那种兜底残留 |

---

## 三、第 2 步：统一 GitHub 地址

### 3.1 替换范围

正式地址：`https://github.com/stevencui581/WKL-LLM-Ops-Platform`

| 形态 | 说明 |
| --- | --- |
| `https://github.com/<org>/<repo>` | 仓库主页 |
| `https://raw.githubusercontent.com/<org>/<repo>` | **一键脚本的 curl 地址** —— 用户复制的就是这一行 |
| `https://github.com/<org>/<repo>.git` | clone 地址 |
| `<org>/<repo>` | 裸形式（徽章等） |

**结果：15 个文件，76 处替换。**

### 3.2 连带修改：克隆后的目录名

仓库从旧名改名为 `WKL-LLM-Ops-Platform` 之后，`git clone` 生成的目录名、
压缩包解压后的目录名都随之改变。文档里若仍写旧目录名，**用户照抄就会失败**。

已同步 **13 个文件**：`cd ~/WKL-LLM-Ops-Platform`、`mv WKL-LLM-Ops-Platform-main …`、
`/opt/WKL-LLM-Ops-Platform`、`install.sh` 的默认安装目录、`deploy/conn.py` 的默认根目录。

### 3.3 未改动项（有意保留）

| 项 | 原因 |
| --- | --- |
| Python 发行包名 `wkl-llm-ops`（未随仓库改名） | 独立于 GitHub 仓库名，属正常做法 |
| 第三方地址（promptfoo / hermes-agent / vLLM-2080Ti / OpenJS） | 是参考资料，**必须原样保留** |

守卫 `test_third_party_urls_untouched` 专门盯这一点，防止"统一替换"误伤引用来源。

### 3.4 守卫抓到的真实缺失

`test_docs_reference_canonical` 报出 **SECURITY.md / SECURITY.zh-CN.md 缺少本项目上报入口** ——
原文只链接了 GitHub 官方文档，没有指向本仓库的私密上报表单。已补齐：

```
https://github.com/stevencui581/WKL-LLM-Ops-Platform/security/advisories/new
```

---

## 四、第 3 步：排版优化（对齐成功案例）

### 4.1 从参考项目学到的排版要素

拉取并研读了 [weicj/vLLM-2080Ti-Definitive](https://github.com/weicj/vLLM-2080Ti-Definitive)
的 README，提取出以下版式特征并全部落地：

| 参考项目特征 | 本项目落地 |
| --- | --- |
| 标题带 Emoji（`# ⚡ …`） | ✅ `# ⚡ WKL-LLM Ops Platform` |
| 标题下紧跟语言切换行 | ✅ `Language: English \| [简体中文](README.zh-CN.md)` |
| 一句话定位 | ✅ 紧随语言行 |
| 独立一行列出仓库 / 版本基线 / 变更日志 | ✅ `Repository:` / `Current baseline:` / `Release history:` |
| **Emoji 分节标题** | ✅ 💡 为什么需要 · 🧩 支持的框架 · 🚀 安装启动 · 🛠️ 硬件要求 · 🧪 质量证据 · ❓ 问答 · 🧭 设计原则 · 📁 目录结构 · 🤝 贡献 · 🙏 致谢 · 📄 许可证 |
| **数字右对齐表格**（`\| ---: \|`） | ✅ 质量证据表 |
| 编号步骤 + 代码块 | ✅ 安装步骤 |
| **❓ 硬件问答节** | ✅ 8 条常见问题直接写进 README |
| **🙏 致谢 / 上游项目节** | ✅ 列出 5 个参考来源 |
| 相对路径链接到详细文档 | ✅ 全部指向 `docs/*.md` |

### 4.2 中英结构严格对等

重写后两版结构完全一致（这是双语文档守卫的硬性要求）：

```
README.md   EN = 标题 12 / 代码块 11 / 表格 34
README.zh-CN.md  ZH = 标题 12 / 代码块 11 / 表格 34
```

全部 6 组顶层文档的结构核对：

| 文档 | 标题 | 代码块 | 表格 |
| --- | ---: | ---: | ---: |
| README | 12 / 12 | 11 / 11 | 34 / 34 |
| CHANGELOG | 32 / 32 | 0 / 0 | 0 / 0 |
| CONTRIBUTING | 10 / 10 | 10 / 10 | 14 / 14 |
| CODE_OF_CONDUCT | 12 / 12 | 0 / 0 | 0 / 0 |
| SECURITY | 9 / 9 | 1 / 1 | 15 / 15 |
| AGENTS | 18 / 18 | 2 / 2 | 17 / 17 |

（格式为 英文 / 中文）

### 4.3 新增术语对照表

`docs/GLOSSARY.md` —— **单文件双语**（一张表两列）：把界面与注释里的中文说法，
与代码、文档、Issue 里的英文说法对应起来，共 31 条术语 + 命名约定。

> 它刻意不做成 `X.md` + `X.zh-CN.md` 两个文件：术语表本身就是中英对照的一张表。
> 守卫里用 `SINGLE_FILE_BILINGUAL` 显式列出并注明原因 —— 不是默默放过。

---

## 五、GitHub 上传：结果与过程

### 5.1 最终结果

| 项 | 结果 |
| --- | --- |
| 仓库 | <https://github.com/stevencui581/WKL-LLM-Ops-Platform> |
| 可见性 | **PUBLIC** |
| 默认分支 | `main` |
| 远程文件数 | **182**（与本地逐项一致） |
| 关键文件核对 | ✅ **68 项全部就位** |
| 敏感内容检查 | ✅ 无凭据、无虚拟环境、无运行时状态、无历史归档 |
| 本地 / 远程 HEAD | ✅ `f037a6b` 完全一致 |
| Topics | ✅ 12 个（llm / llama-cpp / ollama / vllm / sglang / fastapi / systemd / bilingual …） |
| 页面可达性 | ✅ 仓库页、中英 README、`install.sh` 均 HTTP 200 |
| 验收工具 | `tools/verify_remote.py` → `REMOTE_VERIFY_OK` |

### 5.2 凭据：密码认证已废弃，改用 OAuth 设备流

用户最初提供的是**账号密码**。我实测验证了它不能用（不是照搬文档）：

```
=== 用账号密码访问 GitHub API ===
  HTTP 401  -> 未经授权
=== 用账号密码做 git ls-remote ===
  remote: Repository not found
```

GitHub 于 **2021 年 8 月移除密码认证**。

我依次排查了全部凭据路径，并对每一条都给出了确定结论：

| 路径 | 结果 |
| --- | --- |
| 账号密码 | ❌ API 返回 **401** |
| SSH 公钥 | ❌ 已生成但未添加到账号（两轮未完成） |
| Windows 凭据管理器 | ❌ 无 GitHub 条目 |
| `~/.git-credentials` | ❌ 不存在 |
| **OAuth 设备流** | ✅ **成功** |

**最终采用 OAuth 设备流**：用户只需在 <https://github.com/login/device> 输入一个 8 位代码，
不需要管理任何密钥文件。为此临时下载了官方 `gh` CLI（v2.102.0 便携版，无需安装）。

### 5.3 上传过程中遇到的三个真实问题

**① 仓库并不存在**

用户认为仓库已创建，但 `gh repo view` 与账号仓库列表都确认它**不存在**
（`public_repos: 0`，GraphQL 报 `Could not resolve to a Repository`）。
已用 `gh repo create` 创建为 PUBLIC 仓库。

> 这一点值得记录：如果我没核实就推送，会得到 `Repository not found`，
> 而且很容易误判成"权限问题"去反复折腾凭据。

**② 全局 git 改写规则导致凭据助手匹配失败**

本机 `~/.gitconfig` 中存在：

```
url.https://steven-sways@github.com/.insteadof=https://github.com/
```

它会把**所有** `https://github.com/...` 改写成 `steven-sways@github.com`；而 `gh` 写入的
凭据助手是按 `https://github.com` 精确匹配的 —— 两者对不上，推送会退化成"要密码"然后失败。

**未改动用户的全局配置**，而是通过 `GIT_CONFIG_GLOBAL` 指向一份临时配置
（只含 `gh` 凭据助手、不含改写规则）完成推送。

**③ OAuth 令牌缺少 `workflow` 权限**

第一次推送被拒绝：

```
! [remote rejected] main -> main (refusing to allow an OAuth App to create or update
  workflow `.github/workflows/ci.yml` without `workflow` scope)
```

GitHub 对 `.github/workflows/` 下的文件有额外权限要求。已用
`gh auth refresh -h github.com -s workflow` 补充授权后推送成功。

### 5.4 安全提醒

**账号密码已在对话中明文出现**，虽然它无法用于 Git 推送，仍建议立即更换：
<https://github.com/settings/security>

**本次 OAuth 授权可随时撤销**：<https://github.com/settings/applications>

---

## 六、过程中发现并修复的问题

### 6.1 `.github/` 目录在重建发布副本时丢失（**工具缺陷**）

**现象**：把发布副本目录名从 `WKL-LLM-Ops` 改为 `WKL-LLM-Ops-Platform` 后，
`verify_release.py` 报 6 个文件缺失 —— CI 工作流、PR 模板、Issue 模板、Dependabot 全没了。

**根因**：`.github/` 当初是**直接写在发布副本里**的，从未纳入 `build_release.py`
的 `COPY_DIRS`。我重建目录并删掉旧目录后，它就没有第二个副本了。

**修复**：
- 6 个文件重建到**开发树**（唯一事实源），不再只存在于发布副本
- `.github` 加入 `build_release.py` 的 `COPY_DIRS`
- `RELEASE_CHECK_OK` 恢复到 47 个必需文件

**教训**：凡是"手工写在发布副本里"的文件，都会在下一次重建时丢失。
所有源文件必须落在开发树。

### 6.2 `verify_release.py` 的包名检查被误改

第 2 步的目录名替换把 `verify_release.py` 里的包名检查也一并改了
（`!= "<包名>"` 被换成 `!= "WKL-LLM-Ops-Platform"`）—— 但 pyproject 的**发行包名**并未改变，
这个检查会恒失败。已修正并在注释里写明"包名独立于仓库名"。

### 6.3 守卫自身的一个断言过松

`test_docs_reference_canonical` 最初用 `if "github.com" not in text: skip` 做跳过条件，
但 `docs.github.com` 也含 `github.com`，导致跳过逻辑失效 ——
**而这恰好暴露了 SECURITY 文档真的缺少本项目上报入口**（见 §3.4）。
改为检查是否引用本项目仓库。

### 6.4 发布副本里残留了旧版测试报告（**工具副作用**）

**现象**：生成 v0.6 报告后，发布副本的 `docs/` 里**同时存在** v0.5.1 与 v0.6 两份测试报告。

**根因**：`build_release.py` 的 `_clean_managed()` 当初为了"不删手写文件"，
完全跳过了 `docs/` 的清理；`KEEP_DOCS` 只控制**复制什么**，不控制**删除什么**。
于是换成新报告后，旧报告无人清理。

**这是同一条弯路的两端**：早期用整目录 `rmtree` 把人工撰写的文档一起删了；
改成"完全不清理"之后又出现残留。现在的规则是明确的：

> **所有源文件都在开发树里，发布副本是可重建的产物。**
> `docs/` 严格对齐 `KEEP_DOCS` 白名单，其余受管目录整体重建；
> `.git` 不在受管目录内，会被保留。

### 6.5 验证器把 `.git` 内部对象当文本扫描

发布副本本身是 git 仓库，`verify_release.py` 原先遍历所有文件查行尾，
于是把 `.git/objects/pack/*.pack`（二进制）报成 CRLF。
已加入 `SKIP_PARTS`，并抽出 `_release_files()` 统一跳过 `.git` 与各类缓存。

### 6.6 CI 首次推送即失败：`pip install -e '.[dev]'` 无法构建（**真实缺陷**）

**现象**：上传后 CI 的「质量门禁」job 立即失败，其余 5 个 job 通过。

```
error: Multiple top-level packages discovered in a flat-layout:
       ['app', 'static', 'deploy', 'probes']
```

**根因**：`pyproject.toml` 没有声明包范围，setuptools 的自动发现在扁平布局里
看到多个顶层目录就拒绝构建。

**为什么本地从未暴露**：本地虚拟环境是用 `pip install -r requirements.txt` 建的，
**从来没有跑过 `pip install .`**。也就是说这份 `pyproject.toml` 对任何想按标准方式
安装它的人都是坏的 —— 包括贡献者和文档里写的手动安装路径。

**修复**：显式声明构建后端与包范围：

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]
namespaces = false
```

**验证方式**：在服务器上新建一次性 venv，**完整复现 CI 的安装步骤** ——
得到 `Successfully built wkl-llm-ops` / `Successfully installed wkl-llm-ops-0.6.0`，
并在该 venv 里跑通 ruff / format / mypy / pytest。

### 6.7 lint 工具版本漂移：「本地全绿、CI 变红」

修好构建之后，CI 暴露出**第二个**问题：干净 venv 里的 ruff 报出 2 个错
（`SIM102` 嵌套 if、`F841` 未使用变量），而本地 ruff 一个都不报。

| 工具 | 本地 venv | CI 干净 venv |
| --- | --- | --- |
| ruff | 0.16.9 | **0.16.10** |
| mypy | 2.3.1 | **2.4.0** |

**根因**：dev 依赖写的是 `ruff>=0.6`、`mypy>=1.11`。ruff 的**检查规则会随小版本增减**，
CI 装最新版、本地停在旧版时，两边跑的根本不是同一把尺子。

**修复**：静态检查工具**按小版本锁定**（`~=` 允许补丁级更新）：`ruff~=0.16.10`、
`mypy~=2.4.0`，并同步升级本地 venv。

### 6.8 GitHub Actions 使用已弃用的 Node 20

CI 注解提示 `actions/checkout@v4`、`actions/setup-node@v4` 使用的 Node 20 已弃用。
核实最新版本后（checkout v7.0.1、setup-python v7.0.0、setup-node v7.0.0）全部升级到 v7。

同时把 `ludeeus/action-shellcheck@master` 改为固定版本 `@2.0.0` ——
引用可变分支意味着上游随时可以改变 CI 行为，对开源项目的供应链安全不利。

**修复后 CI 结果**：**6/6 job 全绿**（前端渲染冒烟 / 质量门禁 / 行尾与 BOM / 一键脚本 / shellcheck / 前端静态）。

> Dependabot 在仓库建立后几分钟内就自动开了 3 个版本升级 PR，
> 说明 `.github/dependabot.yml` 配置生效。由于改动已直接进入 main，这 3 个 PR 已关闭。

> **共性教训**：这三个问题本地全都测不出来 —— 因为它们依赖
> 「干净环境 + 最新工具 + GitHub 侧的限制」。本地门禁再全，也替代不了**在目标环境里真跑一遍**。

---

## 七、遗留问题

| # | 项 | 性质 | 说明 |
| --- | --- | --- | --- |

| L2 | 一键脚本未在全新机器上端到端验证 | 验证范围 | 幂等路径已在真实环境验证；首次安装路径依赖全新环境 |
| L3 | 多框架支持仍只在 llama.cpp 上做过真机验证 | 覆盖度 | Ollama / vLLM / SGLang 由假响应单测覆盖（25 项） |
| L3 | 全局 git URL 改写规则未清理 | 环境 | 本次用临时配置绕过；是否清理本机全局配置需用户决定 |
| L5 | 72 小时稳定性观察未满 | 时间性 | 部署以来 0 重启、0 readiness 失败 |

---

## 八、交付物

| 交付物 | 路径 |
| --- | --- |
| **发布副本（待推送）** | `WKL-LLM-Ops-Platform/` |
| 本报告 | `docs/WKL-LLM运维平台_v0.6升级测试报告.md` / `.docx` |
| 术语对照表 | `docs/GLOSSARY.md` |
| 配置档案（按框架） | `examples/{llama-cpp,ollama,vllm,sglang}.env` + `examples/README.md` |
| 版本升级工具 | `tools/bump_version.py` |
| 地址统一工具 | `tools/fix_repo_url.py` / `tools/fix_repo_dirname.py` |
| 一致性守卫 | `tests/test_repo_consistency.py` |

---

## 九、结论

**三步全部完成：版本号统一、地址统一、项目已正式上传到 GitHub 并通过远程验收。**

1. **版本号真正统一**：不是无脑全文替换，而是区分「当前版本」与「历史标注」——
   后者必须保留，否则等于篡改开发记录。并新增 26 项守卫防止将来再漏。
2. **仓库地址统一且不误伤**：76 处替换 + 克隆目录名同步；
   同时用守卫保护第三方引用不被"统一替换"波及。
3. **排版对齐成功案例**：Emoji 分节、语言切换行、❓问答节、🙏致谢节、数字右对齐表格，
   中英两版结构严格对等。
4. **过程中修掉 3 个问题**，其中 `.github/` 丢失是**工具缺陷**——
   根因是文件只存在于发布副本、没有落到开发树。

**必须诚实指出**：用户最初提供的**账号密码无法用于 GitHub 推送**（实测 401），
最终通过 **OAuth 设备流**完成授权；另外用户以为已创建的仓库**实际并不存在**，
已代为创建。这两点如果没核实就动手，都会表现为权限问题而让人在凭据上反复折腾。

---

*报告生成时间：2026-10-04　　被测版本：v0.6（release 20261004-001900）*
*开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01*
