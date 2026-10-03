# WKL-LLM运维平台 v0.6 升级测试报告

**主题：正式发布 —— 版本号统一 · 仓库地址统一 · 排版对齐成功案例 · GitHub 上传准备**

| 项 | 内容 |
| --- | --- |
| **被测版本** | **v0.6**（基线 v0.5.1） |
| **部署版本** | `releases/20261004-001900` |
| **正式仓库** | <https://github.com/stevencui581/WKL-LLM-Ops-Platform> |
| **测试日期** | 2026-10-04 |
| **测试结论** | **通过** —— 质量门禁 4/4、验收套件 **10/10**、自动化测试 **425 项**、仓库一致性守卫 **26 项**、双语文档守卫 **56 项**、发布副本自检 **9 项 / 47 个必需文件** |

> **开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01**

---

## 一、结论摘要

| 步骤 | 任务 | 结果 |
| --- | --- | --- |
| 1 | 升级到 v0.6，统一全项目版本号 | ✅ 代码 / 文档 / 脚本全部统一；新增版本一致性守卫 |
| 2 | 统一 GitHub 地址为正式仓库 | ✅ **76 处**替换；含克隆目录名同步；新增地址一致性守卫 |
| 3 | 上传到 GitHub + 按成功案例优化排版 | ⏳ 仓库与提交已就绪，**待 SSH 公钥添加到你的账号后一条命令推送**；排版已完成 |

| 指标 | 结果 |
| --- | --- |
| 质量门禁 | ✅ ruff 全过、89 文件格式合规、mypy 40 文件无错 |
| 自动化测试 | ✅ **425 项全通过**（较 v0.5.1 的 399 项 **+26**） |
| 端到端验收 | ✅ **10/10 OK** |
| 仓库一致性守卫 | ✅ **26 项**（版本号 5 组 + 地址 10 组 + 目录名 + 第三方保护） |
| 发布副本自检 | ✅ **9 项 / 47 个必需文件** |
| 本地 git 仓库 | ✅ 已提交，177 个文件，分支 `main` |
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

## 五、GitHub 上传：已完成的部分与阻塞点

### 5.1 已完成

| 项 | 状态 |
| --- | --- |
| 发布副本 `WKL-LLM-Ops-Platform/` | ✅ 177 个文件，`RELEASE_CHECK_OK` |
| 目录名与仓库名对齐 | ✅ |
| 本地 git 仓库初始化 | ✅ 分支 `main` |
| 首次提交 | ✅ `73b7c4a`（177 个文件） |
| 远程地址配置 | ✅ `git@github.com:stevencui581/WKL-LLM-Ops-Platform.git` |
| SSH 密钥生成 | ✅ `~/.ssh/id_ed25519_wkl`（ed25519） |
| SSH 连通性 | ✅ 握手成功，仅密钥未注册 |

### 5.2 阻塞点：GitHub 已废弃密码认证

用户提供的是账号密码。**我实测验证了它不能用**（不是照搬文档）：

```
=== 用账号密码访问 GitHub API ===
  HTTP 401  -> 未经授权
=== 用账号密码做 git ls-remote ===
  remote: Repository not found
```

GitHub 于 **2021 年 8 月移除密码认证**，`git push` 必须使用 SSH key 或 Personal Access Token。

**用户已选择 SSH key 方式**，公钥已生成并提供给用户：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF61kM9TaAMayUBnZ748xfsjR6rQMIcHxYwSWWBHqjXz stevencui581@gmail.com
```

添加到 <https://github.com/settings/keys> 后，执行 `git push -u origin main` 即可完成。

### 5.3 过程中发现的两个环境问题

**① 全局 git 配置会破坏推送到本账号**

本机 `~/.gitconfig` 中存在：

```
url.https://steven-sways@github.com/.insteadof=https://github.com/
```

它会把**所有** `https://github.com/...` 地址改写成以 `steven-sways` 用户认证 ——
与目标账号 `stevencui581` 不符。**未擅自修改全局配置**，只在本仓库改用 SSH 形式绕过
（`ssh://git@github.com:` 形式仍会被另一条规则改写，因此使用 scp 形式的
`git@github.com:...`）。

> 若本机还有其它仓库要推送到 `stevencui581`，同样会踩到这条规则。

**② 安全提醒：账号密码已在对话中明文出现**

虽然该密码无法用于 Git 推送，仍建议立即更换：<https://github.com/settings/security>

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

---

## 七、遗留问题

| # | 项 | 性质 | 说明 |
| --- | --- | --- | --- |
| L1 | **推送尚未完成** | 阻塞 | 等 SSH 公钥添加到 GitHub 账号 |
| L2 | 一键脚本未在全新机器上端到端验证 | 验证范围 | 幂等路径已在真实环境验证；首次安装路径依赖全新环境 |
| L3 | 多框架支持仍只在 llama.cpp 上做过真机验证 | 覆盖度 | Ollama / vLLM / SGLang 由假响应单测覆盖（25 项） |
| L4 | 全局 git URL 改写规则未清理 | 环境 | 只在本仓库绕过；是否清理全局配置需用户决定 |
| L5 | 72 小时稳定性观察未满 | 时间性 | 部署以来 0 重启、0 readiness 失败 |

---

## 八、交付物

| 交付物 | 路径 |
| --- | --- |
| **发布副本（待推送）** | `WKL-LLM-Ops-Platform/` |
| 本报告 | `docs/WKL-LLM运维平台_v0.6升级测试报告.md` / `.docx` |
| 术语对照表 | `docs/GLOSSARY.md` |
| 版本升级工具 | `tools/bump_version.py` |
| 地址统一工具 | `tools/fix_repo_url.py` / `tools/fix_repo_dirname.py` |
| 一致性守卫 | `tests/test_repo_consistency.py` |

---

## 九、结论

**第 1、2 步完成并通过全部验收；第 3 步已完成除推送外的全部准备。**

1. **版本号真正统一**：不是无脑全文替换，而是区分「当前版本」与「历史标注」——
   后者必须保留，否则等于篡改开发记录。并新增 26 项守卫防止将来再漏。
2. **仓库地址统一且不误伤**：76 处替换 + 克隆目录名同步；
   同时用守卫保护第三方引用不被"统一替换"波及。
3. **排版对齐成功案例**：Emoji 分节、语言切换行、❓问答节、🙏致谢节、数字右对齐表格，
   中英两版结构严格对等。
4. **过程中修掉 3 个问题**，其中 `.github/` 丢失是**工具缺陷**——
   根因是文件只存在于发布副本、没有落到开发树。

**必须诚实指出**：**推送这一步没有完成** —— 需要一个已注册到 GitHub 账号的 SSH 公钥。
仓库、提交、远程、密钥都已就绪，只差把公钥加到账号里。

---

*报告生成时间：2026-10-04　　被测版本：v0.6（release 20261004-001900）*
*开发者信息：WKL-LLM运维平台　　开发日期：2026.10.01*
