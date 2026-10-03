"""双语文档一致性守卫（v0.6）。

**为什么需要**

    项目要求所有文档都有英文（``X.md``）与中文（``X.zh-CN.md``）两个版本。
    这类要求最容易随时间腐化：改了英文忘了中文，或者新增文档只写一种语言。
    静态守卫能立刻发现，而不是等用户看到半截文档。

本文件守卫四件事：

  1. **成对存在** —— 每个 ``X.md`` 都有 ``X.zh-CN.md``，反之亦然
  2. **结构对等** —— 两个版本的标题层级序列、代码块数、表格行数一致
  3. **英文版无中文正文** —— 唯一允许的 CJK 是语言切换链接里的 `中文` 标签
  4. **中文版无「未翻译」占位** —— 不允许 TODO/TBD/待翻译 这类残留
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: **单文件双语**的文档：本身一张表两列，不需要 .zh-CN 对应文件。
#: 明确列出而不是默默放过 —— 新增文档时要么成对，要么在这里说明原因。
SINGLE_FILE_BILINGUAL = (
    "docs/GLOSSARY.md",
    "examples/README.md",
)

#: 必须成对存在的文档（相对仓库根）
BILINGUAL_PAIRS = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/INSTALL.md",
    "docs/ARCHITECTURE.md",
    "docs/CONFIGURATION.md",
    "docs/API.md",
    "docs/FAQ.md",
    "docs/TROUBLESHOOTING.md",
)

CJK = re.compile(r"[\u4e00-\u9fff]")

#: 英文文档中**允许**出现中文的上下文。
#:
#: 本守卫要拦的是"英文文档里混着未翻译的中文段落"，
#: 而不是把所有中文一律禁掉 —— 下面这些是合理且必要的：
#:
#:   * 语言切换链接的标签（``[中文]`` / ``[中文说明]``）
#:   * 行内代码与代码块（可能是配置值、期望输出、示例数据）
#:   * 对"中文"这门语言本身的提及
ALLOWED_CONTEXTS = (
    r"\[[^\]]*中文[^\]]*\]\([^)]*\)",  # 语言切换链接
    r"`[^`]*`",  # 行内代码
    r"中文",  # 「中文」这个词本身
)


def _strip_allowed_contexts(line: str) -> str:
    """去掉允许出现中文的片段，返回需要检查的剩余文本。"""
    for pattern in ALLOWED_CONTEXTS:
        line = re.sub(pattern, "", line)
    return line


def _zh_path(rel: str) -> Path:
    p = ROOT / rel
    return p.with_name(p.stem + ".zh-CN.md")


def _headings(text: str) -> list[int]:
    """标题层级序列（# 的个数），忽略代码块内部的 # 注释。"""
    levels: list[int] = []
    in_fence = False
    for line in text.splitlines():
        s = line.rstrip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+\S", s)
        if m:
            levels.append(len(m.group(1)))
    return levels


def _fence_count(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip().startswith("```")) // 2


def _table_rows(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip().startswith("|"))


# ===========================================================================
# 1. 成对存在
# ===========================================================================
@pytest.mark.parametrize("rel", BILINGUAL_PAIRS)
def test_bilingual_pair_exists(rel: str):
    """每份公开文档都必须有英文与中文两个版本。"""
    en = ROOT / rel
    zh = _zh_path(rel)
    assert en.is_file(), f"缺少英文文档：{rel}"
    assert zh.is_file(), f"缺少中文文档：{zh.relative_to(ROOT)}"


# ===========================================================================
# 2. 结构对等
# ===========================================================================
@pytest.mark.parametrize("rel", BILINGUAL_PAIRS)
def test_bilingual_structure_matches(rel: str):
    """两个版本的标题层级、代码块数、表格行数必须一致。

    翻译可以改变行数与措辞，但不该改变**结构** —— 结构不一致通常意味着
    其中一版漏了章节或漏了示例。
    """
    en = (ROOT / rel).read_text(encoding="utf-8")
    zh = _zh_path(rel).read_text(encoding="utf-8")

    assert _headings(en) == _headings(zh), (
        f"{rel} 与中文版标题层级不一致：\n  EN={_headings(en)}\n  ZH={_headings(zh)}"
    )
    assert _fence_count(en) == _fence_count(zh), (
        f"{rel} 与中文版代码块数量不一致：EN={_fence_count(en)} ZH={_fence_count(zh)}"
    )
    assert _table_rows(en) == _table_rows(zh), (
        f"{rel} 与中文版表格行数不一致：EN={_table_rows(en)} ZH={_table_rows(zh)}"
    )


# ===========================================================================
# 3. 英文版不得有中文正文
# ===========================================================================
@pytest.mark.parametrize("rel", BILINGUAL_PAIRS)
def test_english_doc_has_no_cjk_body(rel: str):
    """英文文档正文不得含中文。

    允许的例外见 ``ALLOWED_CONTEXTS``：语言切换链接、行内代码与「中文」这个词本身。
    要拦的是**未翻译的中文段落**，不是一切中文。
    """
    text = (ROOT / rel).read_text(encoding="utf-8")
    bad: list[str] = []
    in_fence = False
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # 代码块里可能是任何语言的示例数据
        if not CJK.search(ln):
            continue
        if CJK.search(_strip_allowed_contexts(ln)):
            bad.append(f"{rel}:{i}: {ln.strip()[:90]}")
    assert not bad, "英文文档里出现未翻译的中文正文：\n" + "\n".join(bad)


# ===========================================================================
# 4. 中文版不得有未翻译占位
# ===========================================================================
@pytest.mark.parametrize("rel", BILINGUAL_PAIRS)
def test_no_untranslated_placeholders(rel: str):
    """不允许留下 TODO / TBD / 待翻译 之类的占位。"""
    for path in (ROOT / rel, _zh_path(rel)):
        text = path.read_text(encoding="utf-8")
        for i, ln in enumerate(text.splitlines(), 1):
            low = ln.lower()
            assert "待翻译" not in ln, f"{path.name}:{i} 存在待翻译占位"
            assert "todo:" not in low, f"{path.name}:{i} 存在 TODO 占位"
            assert "tbd" not in low or low.strip() == "tbd", f"{path.name}:{i} 存在 TBD 占位"


# ===========================================================================
# 5. 一键脚本与语言切换链接
# ===========================================================================
def test_install_scripts_present():
    for name in ("install.sh", "update.sh", "uninstall.sh"):
        p = ROOT / name
        assert p.is_file(), f"缺少仓库根的一键脚本：{name}"
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} 不应带 BOM"
        assert b"\r\n" not in raw, f"{name} 不应是 CRLF 行尾"
        assert raw.split(b"\n", 1)[0].startswith(b"#!/usr/bin/env bash"), f"{name} 首行必须是 bash shebang"


def test_docs_have_language_switcher():
    """每份双语文档都要有指向**另一个语言版本**的切换链接。

    必须精确指向自己的对应文件（``X.md`` ↔ ``X.zh-CN.md``），
    而不是随便某个 .md 链接 —— 否则读者点过去会到了另一篇文档。
    """
    for rel in BILINGUAL_PAIRS:
        en_path = ROOT / rel
        zh_path = _zh_path(rel)
        en_name = en_path.name
        zh_name = zh_path.name

        en = en_path.read_text(encoding="utf-8")
        zh = zh_path.read_text(encoding="utf-8")

        assert f"({zh_name})" in en, f"{en_name} 缺少指向 {zh_name} 的切换链接"
        assert f"({en_name})" in zh, f"{zh_name} 缺少指向 {en_name} 的切换链接"


def test_env_example_covers_key_settings():
    """`.env.example` 必须覆盖部署时最常改的几项。"""
    p = ROOT / ".env.example"
    assert p.is_file(), "缺少 .env.example"
    text = p.read_text(encoding="utf-8")
    for key in (
        "LLMCONSOLE_LLAMA_UNIT",
        "LLMCONSOLE_LLAMA_BASE_URL",
        "LLMCONSOLE_PORT",
        "LLMCONSOLE_LOG_LEVEL",
    ):
        assert key in text, f".env.example 未包含 {key}"
    # 不得含真实主机或凭据
    for bad in ("172.", "192.168", "tbea", "password="):
        assert bad not in text.lower(), f".env.example 含疑似真实值：{bad}"


def test_gitattributes_enforces_lf():
    """`.gitattributes` 必须声明 LF —— 这是 CRLF 类缺陷的第一道防线。"""
    p = ROOT / ".gitattributes"
    assert p.is_file(), "缺少 .gitattributes"
    text = p.read_text(encoding="utf-8")
    assert "eol=lf" in text, ".gitattributes 未强制 LF 行尾"
    # 无扩展名的关键文件最容易漏，必须显式列出
    for name in ("install.sh", "selfcheck.sh"):
        assert name in text, f".gitattributes 未显式声明 {name}"
