"""路由包。"""

from __future__ import annotations

from fastapi import FastAPI

from . import data, hardware, health, history, overview, service


def register(app: FastAPI) -> None:
    for mod in (overview, data, health, service, hardware, history):
        app.include_router(mod.router, tags=[mod.__name__.rsplit(".", 1)[-1]])
