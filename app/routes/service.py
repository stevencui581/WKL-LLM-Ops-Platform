"""服务管理端点（方案 TASK-14 / 7.6）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ._deps import ctx

router = APIRouter()


@router.get("/api/service/status")
async def status(request: Request) -> dict:
    c = ctx(request)
    st = await c.service.status()

    # 判定「真的恢复了」不能用 systemd 的 ActiveState：`systemctl restart` 返回时
    # 进程已 active，但 llama-server 还在加载模型、端口尚未监听（实测约 8 秒）。
    # 用 llama-server 的可达性来修正进度文案，并真正结束这次操作窗口。
    if st.elapsed_s is not None:
        reachable, _, _ = await c.client.health()
        if reachable:
            st.progress = "已恢复"
            c.service.clear_operation()
            st.elapsed_s = None
        else:
            st.progress = "模型加载中（端口尚未响应）"

    if c.service.authorized is False:
        st.authorized = False
    body = st.model_dump()
    # 运维需要知道「为什么未授权」，否则只能看到一句笼统的提示
    body["auth_error"] = c.service.authorization_error
    body["probe_error"] = c.service.last_probe_error
    body["sudoers_hint"] = c.service.sudoers_hint if st.authorized is False else None
    return body


@router.post("/api/service/{action}")
async def do_action(request: Request, action: str):
    c = ctx(request)
    ok, message, code = await c.service.do_action(action)
    body = {
        "ok": ok,
        "action": action,
        "unit": c.settings.llama_unit,
        "message": message,
        "eta_s": c.settings.restart_eta_seconds,
    }
    if not ok:
        if code == 403:
            body["sudoers"] = c.service.sudoers_hint
        if code == 400:
            return JSONResponse(body, status_code=400)
        if code == 409:
            return JSONResponse(body, status_code=409)
        if code == 403:
            return JSONResponse(body, status_code=403)
        return JSONResponse(body, status_code=500)
    return JSONResponse(body, status_code=202)
