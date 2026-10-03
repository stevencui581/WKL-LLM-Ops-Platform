"""服务管理封装（方案 TASK-14 / 7.6）。

安全约束：
  * 只调用固定的三条命令，参数走白名单校验，**禁止拼接任意命令**；
  * ``subprocess`` 一律使用参数列表（``shell=False``）；
  * 未授权时返回明确原因与所需 sudoers 命令文本，界面改为只读提示。
"""

from __future__ import annotations

import contextlib
import logging
import time

from ..adapters.exec import CommandRunner
from ..config import Settings
from ..models import ServiceStatus

log = logging.getLogger("llmconsole.service")


class ServiceController:
    def __init__(self, settings: Settings, runner: CommandRunner):
        self.s = settings
        self.runner = runner
        self.busy = False
        self._op_started: float | None = None
        self._op_action: str | None = None
        self.authorized: bool | None = None
        self.authorization_error: str | None = None
        self.last_probe_error: str | None = None

    # ------------------------------------------------------------------
    @property
    def run_user(self) -> str:
        """当前运行用户 —— 动态获取，**不写死**（v0.4 F9 修复）。"""
        try:
            import getpass

            return getpass.getuser()
        except Exception:  # noqa: BLE001 - 极端环境下 getpass 可能失败
            import os

            return os.environ.get("USER") or os.environ.get("LOGNAME") or "root"

    @property
    def sudoers_hint(self) -> str:
        s = self.s
        user = self.run_user
        acts = "".join(
            f"                            /usr/bin/systemctl {a} {s.llama_unit}"
            + (", \\\n" if a != "reset-failed" else "")
            for a in ("restart", "stop", "start", "reset-failed")
        )
        return (
            "# /etc/sudoers.d/llm-console\n"
            f"# 由 {s.product_name} 生成；用户名为运行期自动探测结果\n"
            f"{user} ALL=(root) NOPASSWD: {acts}"
        )

    def validate_action(self, action: str) -> tuple[bool, str]:
        if action not in self.s.service_actions:
            return False, f"action not allowed: {action!r}（白名单：{list(self.s.service_actions)}）"
        if any(c in action for c in " ;|&$`\n\\'\""):
            return False, "action contains illegal characters"
        return True, ""

    # ------------------------------------------------------------------
    async def check_authorization(self) -> bool:
        """探测免密授权；结果缓存。

        注意：本项目用的是**最小化白名单**（只放行 llm-infer.service 的几个
        动作），所以 ``sudo -n true`` 必然失败 —— 它不在白名单里。
        必须用白名单内且无副作用的命令探测：``systemctl reset-failed``
        对运行中的单元是空操作，正是合适的探针。
        若白名单更宽（配置了通用 NOPASSWD），再回退到 ``sudo -n true``。
        """
        probe = [self.s.systemctl, "reset-failed", self.s.llama_unit]
        res = await self.runner.run(["sudo", "-n", *probe], timeout_s=3, label="sudo-check")
        if res.ok:
            self.authorized = True
            self.authorization_error = None
            return True
        # 把真实错误留下来，否则运维只看到「未授权」，排查成本很高
        self.last_probe_error = (res.stderr or "").strip() or res.error or f"rc={res.returncode}"
        res2 = await self.runner.run(["sudo", "-n", "true"], timeout_s=3, label="sudo-check-any")
        self.authorized = bool(res2.ok)
        self.authorization_error = (
            None if res2.ok else f"需要免密 sudo 授权（见 sudoers 白名单）；探针返回：{self.last_probe_error}"
        )
        return bool(res2.ok)

    async def status(self) -> ServiceStatus:
        res = await self.runner.run(
            [
                self.s.systemctl,
                "show",
                self.s.llama_unit,
                "-p",
                "ActiveState,SubState,ExecMainStartTimestamp,NRestarts,ActiveEnterTimestamp,"
                "ActiveEnterTimestampMonotonic",
            ],
            timeout_s=3,
            label="systemctl-show",
        )
        st = ServiceStatus(
            unit=self.s.llama_unit,
            eta_s=self.s.restart_eta_seconds,
            busy=self.busy,
            authorized=self.authorized is not False,
        )
        if not res.ok:
            return st
        props: dict[str, str] = {}
        for line in res.stdout.splitlines():
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
        st.active = props.get("ActiveState", "unknown")
        st.sub = props.get("SubState", "unknown")
        st.since = props.get("ActiveEnterTimestamp") or props.get("ExecMainStartTimestamp") or ""
        # v0.4 决策 B1：顶栏「服务运行」用 systemd 的单调启动时间戳计算。
        # 用 Monotonic（微秒，CLOCK_MONOTONIC）而不是墙钟字符串，
        # 可以直接与 time.monotonic() 相减，避开时区/格式解析。
        try:
            enter_us = int(props.get("ActiveEnterTimestampMonotonic") or 0)
        except ValueError:
            enter_us = 0
        st.uptime_s = round(time.monotonic() - enter_us / 1_000_000.0, 1) if enter_us > 0 else None
        try:
            st.n_restarts = int(props.get("NRestarts") or 0)
        except ValueError:
            st.n_restarts = 0

        if self._op_started is not None:
            st.elapsed_s = round(time.monotonic() - self._op_started, 1)
            st.progress_code, st.progress = self._progress_label(st.active, st.sub, st.elapsed_s)
        elif st.active == "active":
            st.progress_code, st.progress = "running", "运行中"
        else:
            st.progress_code = st.active or "unknown"
        return st

    @staticmethod
    def _progress_label(active: str, sub: str, elapsed: float) -> tuple[str, str]:
        """返回 ``(progress_code, 中文文案)``。

        v0.4.3 §6.4：``progress_code`` 是**语言无关**的稳定枚举，
        前端按当前语言渲染；``progress`` 中文串保留作向后兼容。
        """
        if active == "activating" or sub in ("start", "start-pre", "auto-restart"):
            if elapsed < 20:
                return "starting", "正在启动"
            return "model_loading", "模型加载中"
        if active == "active":
            # 进程起来了但端口可能还没监听（模型加载中），
            # 真正的「已恢复」由路由层用 llama-server 可达性判定。
            return "waiting_ready", "服务已启动，等待模型就绪"
        if active == "failed":
            return "failed", "启动失败"
        return f"{active}/{sub}", f"{active}/{sub}"

    # ------------------------------------------------------------------
    async def do_action(self, action: str) -> tuple[bool, str, int]:
        ok, err = self.validate_action(action)
        if not ok:
            return False, err, 400
        if self.busy:
            return False, "已有服务操作正在进行", 409
        if self.authorized is None:
            await self.check_authorization()
        if not self.authorized:
            return False, f"未授权：{self.authorization_error}", 403

        argv = ["sudo", "-n", self.s.systemctl, action, self.s.llama_unit]
        self.busy = True
        self._op_started = time.monotonic()
        self._op_action = action
        log.warning("service action requested: %s", action)
        try:
            res = await self.runner.run(argv, timeout_s=60, label=f"systemctl-{action}")
        finally:
            self.busy = False
        if not res.ok:
            self._op_started = None
            return False, res.error or res.stderr[:300] or f"rc={res.returncode}", 500
        # restart/start 后保留计时，供界面显示进度
        if action == "stop":
            self._op_started = None
        return True, "accepted", 202

    def operation_elapsed(self) -> float | None:
        if self._op_started is None:
            return None
        return time.monotonic() - self._op_started

    def clear_operation(self) -> None:
        self._op_started = None
        self._op_action = None

    async def reset_failed(self) -> None:
        """命中 StartLimit 后 unit 处于 failed，必须 reset-failed 才能再次启动。"""
        with contextlib.suppress(Exception):
            await self.runner.run(
                ["sudo", "-n", self.s.systemctl, "reset-failed", self.s.llama_unit],
                timeout_s=10,
                label="systemctl-reset-failed",
            )
