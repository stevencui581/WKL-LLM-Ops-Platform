"""主应用运行时守卫（v0.6.1 现场缺陷回归）。

覆盖两个真实问题：

  1. ``/favicon.ico`` 用 ``JSONResponse(status_code=204, content=None)`` 返回，
     starlette 会写出 ``null`` 正文，而 204 必须无正文 —— 浏览器每次请求图标
     都会在服务端抛
     ``RuntimeError: Response content longer than Content-Length``。
  2. 框架识别结果没有存回 ``Container.framework``，导致采集循环**永远**
     认为"尚未识别"，每 ``framework_redetect_s`` 秒重探一次并重复打日志；
     推理服务重启期间还会反复把已识别框架覆盖成 unknown。
"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.main import _detect_framework_task, build_container
from app.services import framework as fw


def test_favicon_returns_empty_204():
    """回归：/favicon.ico 必须返回无正文的 204。"""
    from app.main import create_app

    app = create_app()
    route = next(r for r in app.routes if getattr(r, "path", None) == "/favicon.ico")
    resp = asyncio.run(route.endpoint())
    assert resp.status_code == 204
    assert resp.body == b"", f"204 不应有正文，实际 {resp.body!r}"


def _fake_info() -> fw.FrameworkInfo:
    info = fw.FrameworkInfo()
    info.id = "vllm"
    info.confidence = "exact"
    info.capabilities = [fw.CAP_METRICS, fw.CAP_MODELS]
    info.metrics_map = dict(fw.SPECS_BY_ID["vllm"].metrics_map)
    return info


async def test_detect_task_stores_framework_on_container(tmp_path, monkeypatch):
    """回归：识别结果必须写回 c.framework，否则会无限重探。"""
    c = build_container(Settings(state_dir=str(tmp_path / "state")))
    info = _fake_info()

    async def fake_detect(_probe):
        return info

    monkeypatch.setattr("app.main.detect_framework", fake_detect)
    assert c.framework is None
    await _detect_framework_task(c)
    assert c.framework is info, "识别结果没有存回容器 —— 采集循环会永久重探"
    assert c.aggregator.framework is info
    # 能力开关也随之生效（vLLM 没有 /props，但指标应可用）
    assert c.aggregator._metrics_enabled() is True
