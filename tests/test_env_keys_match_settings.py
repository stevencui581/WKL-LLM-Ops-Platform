"""环境变量键必须与 ``Settings`` 字段一致（v0.6.1 回归）。

**真实事故**

    ``install.sh`` 会在安装目录生成 ``.env``，其中包含
    ``LLMCONSOLE_LOG_LEVEL=INFO``；``.env.example``、``examples/*.env`` 与
    systemd 单元模板里也有同一行。

    但 ``Settings`` 当时**没有** ``log_level`` 字段，而它设置了
    ``extra="forbid"`` —— pydantic-settings 会把所有带 ``LLMCONSOLE_`` 前缀、
    却没有对应字段的环境变量当成"拼写错误"放进 extra。于是：

        import app.main
        pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
        llmconsole_log_level
          Extra inputs are not permitted

    一键安装在第 6 步（自检）失败，而且**单元测试完全测不出来** ——
    测试环境里没有那份 .env。

本文件把"文档/脚本里写出的每个键，都必须是真字段"变成机器可校验的关系，
并用真 `.env` 做一次启动级回归。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent

#: 会被最终用户照抄或由脚本自动生成的环境变量键（机器读取，不是散文）。
#: 注释掉的键**也**要校验：用户取消注释后必须有效。
SOURCES = (
    ".env.example",
    "install.sh",
    "deploy/llm-console.service",
)

KEY_RE = re.compile(r"\b(LLMCONSOLE_[A-Z0-9_]+)\b")


def _documented_keys() -> set[str]:
    keys: set[str] = set()
    paths = [ROOT / s for s in SOURCES]
    paths += sorted((ROOT / "examples").glob("*.env"))
    for p in paths:
        if not p.is_file():
            continue
        for m in KEY_RE.finditer(p.read_text(encoding="utf-8")):
            keys.add(m.group(1))
    return keys


def test_documented_keys_are_found():
    """前提：确实解析到了键（防止正则失效后测试静默变成空集）。"""
    keys = _documented_keys()
    assert len(keys) >= 10, f"只解析到 {len(keys)} 个键，正则可能失效"
    assert "LLMCONSOLE_LOG_LEVEL" in keys


def test_all_documented_env_keys_are_settings_fields():
    """文档/脚本里出现的每个 ``LLMCONSOLE_*`` 键都必须有对应字段。

    否则 ``extra="forbid"`` 会让服务在启动时直接失败（本文件头的事故）。
    """
    fields = set(Settings.model_fields)
    missing = sorted(key for key in _documented_keys() if key[len("LLMCONSOLE_") :].lower() not in fields)
    assert not missing, (
        f"以下环境变量在文档/脚本里出现，但 Settings 没有对应字段（extra=forbid 会导致启动失败）：{missing}"
    )


# ===========================================================================
# 启动级回归：真的放一份 .env 进去，能加载
# ===========================================================================
def test_settings_load_with_log_level_in_dotenv(tmp_path, monkeypatch):
    """**本缺陷的直接回归**：.env 里有 LLMCONSOLE_LOG_LEVEL 时必须能启动。"""
    (tmp_path / ".env").write_text("LLMCONSOLE_LOG_LEVEL=INFO\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.log_level == "INFO"


def test_settings_load_with_installer_generated_dotenv(tmp_path, monkeypatch):
    """复刻 install.sh 生成的那四行 —— 全新机器上的真实路径。"""
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LLMCONSOLE_LLAMA_UNIT=vllm.service",
                "LLMCONSOLE_LLAMA_BASE_URL=http://127.0.0.1:8000",
                "LLMCONSOLE_PORT=8081",
                "LLMCONSOLE_LOG_LEVEL=INFO",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.llama_unit == "vllm.service"
    assert s.llama_base_url == "http://127.0.0.1:8000"
    assert s.port == 8081
    assert s.log_level == "INFO"


def test_env_var_log_level_also_accepted(monkeypatch):
    """环境变量路径同样必须有效（systemd 单元就是用它）。"""
    monkeypatch.setenv("LLMCONSOLE_LOG_LEVEL", "warning")
    assert Settings().log_level == "WARNING"


# ===========================================================================
# 取值归一与显式失败
# ===========================================================================
def test_log_level_is_uppercased():
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_fails_loudly():
    """拼错级别不能静默降级 —— 与项目「配置错误必须立刻可见」的原则一致。"""
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")
