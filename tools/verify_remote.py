"""核实 GitHub 远程仓库内容（v0.6 上传验收）。"""

from __future__ import annotations

import json
import sys
import urllib.request

REPO = "stevencui581/WKL-LLM-Ops-Platform"
API = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"

KEY_FILES = [
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.zh-CN.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "AGENTS.md",
    "AGENTS.zh-CN.md",
    "CITATION.cff",
    "VERSION",
    ".gitattributes",
    ".gitignore",
    ".editorconfig",
    ".python-version",
    ".env.example",
    "pyproject.toml",
    "conftest.py",
    "selfcheck.sh",
    "install.sh",
    "update.sh",
    "uninstall.sh",
    "docs/README.md",
    "docs/README.zh-CN.md",
    "docs/INSTALL.md",
    "docs/INSTALL.zh-CN.md",
    "docs/ARCHITECTURE.md",
    "docs/ARCHITECTURE.zh-CN.md",
    "docs/CONFIGURATION.md",
    "docs/CONFIGURATION.zh-CN.md",
    "docs/API.md",
    "docs/API.zh-CN.md",
    "docs/FAQ.md",
    "docs/FAQ.zh-CN.md",
    "docs/TROUBLESHOOTING.md",
    "docs/TROUBLESHOOTING.zh-CN.md",
    "docs/GLOSSARY.md",
    "docs/WKL-LLM运维平台_v0.6升级测试报告.md",
    "docs/WKL-LLM运维平台_v0.6升级测试报告.docx",
    "examples/README.md",
    "examples/llama-cpp.env",
    "examples/ollama.env",
    "examples/vllm.env",
    "examples/sglang.env",
    ".github/workflows/ci.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/dependabot.yml",
    "deploy/llm-console.service",
    "deploy/install_service.sh",
    "app/services/framework.py",
    "app/services/aggregator.py",
    "app/models.py",
    "static/index.html",
    "static/app.js",
    "static/i18n.js",
    "tests/test_framework.py",
    "tests/test_docs_bilingual.py",
    "tests/test_repo_consistency.py",
    "tests/test_log_separator.py",
    "tests/test_snapshot_fields.py",
    "probes/e2e_ws_snapshot.py",
    "probes/check_install_scripts.sh",
]

#: 不应出现在公开仓库里的东西。
#:
#: **必须精确匹配** —— 早期版本用子串匹配，把 `app/collectors/history.py`
#: （源码文件）和 `deploy/host.env.example`（应当存在的模板）都误报成了泄漏。
MUST_NOT_EXIST = (
    "deploy/host.env",  # 真实凭据（.example 模板是应当存在的）
    "history/",  # 内部历史归档目录
    "venv/",
    "state/",
    ".backup",
    ".venv/",
)


def _is_leak(path: str) -> str | None:
    """判断路径是否属于不该公开的内容；返回命中的规则或 None。

    目录规则（以 ``/`` 结尾）按路径段匹配；文件规则**必须精确相等** ——
    ``deploy/host.env`` 不能用前缀匹配，否则会把应当存在的
    ``deploy/host.env.example`` 模板误报成凭据泄漏。
    """
    for rule in MUST_NOT_EXIST:
        if rule.endswith("/"):
            if path.startswith(rule) or f"/{rule}" in path:
                return rule
        elif path == rule:
            return rule
    return None


def main() -> int:
    req = urllib.request.Request(API, headers={"User-Agent": "wkl-verify"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    blobs = {t["path"] for t in data["tree"] if t["type"] == "blob"}
    trees = {t["path"] for t in data["tree"] if t["type"] == "tree"}

    print(f"=== 远程仓库 {REPO} ===")
    print(f"  文件数: {len(blobs)}")
    print(f"  目录数: {len(trees)}")
    print(f"  大小  : {data.get('truncated') and '结果被截断' or '完整'}")

    missing = [k for k in KEY_FILES if k not in blobs]
    print(f"\n=== 关键文件核对（{len(KEY_FILES)} 项）===")
    if missing:
        for m in missing:
            print(f"  [缺失] {m}")
    else:
        print("  [全部就位]")

    leaked = [(b, _is_leak(b)) for b in blobs if _is_leak(b)]
    print("\n=== 敏感内容检查 ===")
    if leaked:
        for path, rule in leaked:
            print(f"  !! {path}  (命中规则: {rule})")
    else:
        print("  [OK] 无凭据文件、无虚拟环境、无运行时状态、无历史归档")

    print("\n=== 判定 ===")
    if missing or leaked:
        print("REMOTE_VERIFY_FAILED")
        return 1
    print("REMOTE_VERIFY_OK")
    print(f"  https://github.com/{REPO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
