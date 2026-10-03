"""llama-server HTTP 客户端（适配器层）。

对应方案 TASK-04 / TASK-05 / TASK-09 的数据来源。
所有端点都返回 ``(ok, payload, error)``，**永不抛异常给上层**——
采集循环里任何未捕获异常都会终止采集（V4.1 12.7 第 9 条）。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings


class LlamaClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client
        self._owned = client is None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.s.http_timeout_s),
                headers={"Accept": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, url: str, timeout_s: float | None = None) -> tuple[bool, Any, str | None]:
        t = timeout_s if timeout_s is not None else self.s.http_timeout_s
        try:
            r = await self._c().get(url, timeout=t)
        except Exception as exc:  # noqa: BLE001
            return False, None, f"{type(exc).__name__}: {exc}"
        if r.status_code != 200:
            return False, None, f"HTTP {r.status_code}: {r.text[:200]}"
        try:
            return True, r.json(), None
        except json.JSONDecodeError as exc:
            return False, None, f"invalid json: {exc}"

    async def _get_text(self, url: str, timeout_s: float | None = None) -> tuple[bool, str, str | None]:
        t = timeout_s if timeout_s is not None else self.s.http_timeout_s
        try:
            r = await self._c().get(url, timeout=t)
        except Exception as exc:  # noqa: BLE001
            return False, "", f"{type(exc).__name__}: {exc}"
        if r.status_code != 200:
            return False, r.text, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, r.text, None

    # ------------------------------------------------------------------
    async def slots(self) -> tuple[bool, list[dict] | None, str | None]:
        ok, payload, err = await self._get_json(self.s.slots_url)
        if not ok:
            return False, None, err
        if not isinstance(payload, list):
            return False, None, f"unexpected /slots payload: {type(payload).__name__}"
        return True, payload, None

    async def props(self) -> tuple[bool, dict | None, str | None]:
        ok, payload, err = await self._get_json(self.s.props_url, self.s.props_timeout_s)
        if not ok:
            return False, None, err
        if not isinstance(payload, dict):
            return False, None, "unexpected /props payload"
        return True, payload, None

    async def models(self) -> tuple[bool, dict | None, str | None]:
        ok, payload, err = await self._get_json(self.s.models_url, self.s.props_timeout_s)
        if not ok:
            return False, None, err
        return True, payload if isinstance(payload, dict) else {}, None

    async def metrics(self) -> tuple[bool, str, str | None]:
        """返回 (ok, prometheus 文本, error)。501 时视为「未启用」需永久降级。"""
        return await self._get_text(self.s.metrics_url)

    async def health(self) -> tuple[bool, int, str | None]:
        try:
            r = await self._c().get(self.s.health_url, timeout=self.s.http_timeout_s)
        except Exception as exc:  # noqa: BLE001
            return False, 0, f"{type(exc).__name__}: {exc}"
        return r.status_code == 200, r.status_code, None

    # ------------------------------------------------------------------
    # 通用探测（v0.5 多框架识别用）
    # ------------------------------------------------------------------
    async def probe(self, path: str) -> tuple[bool, Any, str | None]:
        """按**相对路径**探测任意端点，自动判断返回是 JSON 还是文本。

        识别框架时需要问很多不属于 llama.cpp 的端点（``/api/version``、
        ``/v1/models``、``/get_model_info`` …），因此不能复用上面那些
        写死路径的方法。
        """
        url = self.s.llama_base_url.rstrip("/") + path
        t = self.s.http_timeout_s
        try:
            r = await self._c().get(url, timeout=t)
        except Exception as exc:  # noqa: BLE001
            return False, None, f"{type(exc).__name__}: {exc}"
        if r.status_code != 200:
            return False, None, f"HTTP {r.status_code}"
        body = r.text
        try:
            return True, r.json(), None
        except json.JSONDecodeError:
            # 纯文本端点（vLLM 的 /version 就是纯文本）
            return True, body, None
