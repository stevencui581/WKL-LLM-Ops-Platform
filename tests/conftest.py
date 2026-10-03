"""测试夹具：全部使用 253 真实样本，不访问真实网络与真实命令。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llama_base_url="http://127.0.0.1:8080",
        state_dir=str(tmp_path / "state"),
        static_dir=str(tmp_path / "static-none"),
        poll_interval_s=0.05,
        config_poll_interval_s=0.1,
    )


@pytest.fixture(scope="session")
def slots_payload() -> list[dict]:
    return json.loads((FIXTURES / "slots_sample.json").read_text(encoding="utf-8"))["payload"]


@pytest.fixture(scope="session")
def props_payload() -> dict:
    return json.loads((FIXTURES / "props_sample.json").read_text(encoding="utf-8"))["props"]


@pytest.fixture(scope="session")
def models_payload() -> dict:
    return json.loads((FIXTURES / "props_sample.json").read_text(encoding="utf-8"))["models"]


@pytest.fixture(scope="session")
def journal_lines() -> list[str]:
    text = (FIXTURES / "llama_journal_sample.txt").read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


@pytest.fixture(scope="session")
def nvidia_csv() -> str:
    return (FIXTURES / "nvidia_smi_sample.csv").read_text(encoding="utf-8")
