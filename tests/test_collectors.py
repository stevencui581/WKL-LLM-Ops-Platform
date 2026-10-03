"""采集器、降级、WebSocket 背压、服务管理与历史缓冲测试。

对应方案 TASK-11/12/13/14/20/21 的验收标准。
"""

from __future__ import annotations

import asyncio
import json

from app.adapters.exec import CommandRunner
from app.collectors.base import CollectorState, to_int, to_num
from app.collectors.prometheus import PrometheusCollector
from app.collectors.slots import SlotsCollector
from app.models import MetricSnapshot
from app.services.history import History
from app.services.service_ctl import ServiceController


# --------------------------------------------------------------------------
class FakeLlama:
    """可编程的假客户端：可切换成功/超时/501。"""

    def __init__(
        self, slots=None, props=None, models=None, metrics_text=None, metrics_code=200, fail_slots=False
    ):
        self._slots = slots
        self._props = props
        self._models = models
        self._metrics_text = metrics_text
        self._metrics_code = metrics_code
        self.fail_slots = fail_slots
        self.slots_calls = 0
        self.metrics_calls = 0

    async def slots(self):
        self.slots_calls += 1
        if self.fail_slots:
            return False, None, "ConnectTimeout: timeout"
        return True, self._slots, None

    async def props(self):
        return (True, self._props, None) if self._props else (False, None, "HTTP 404")

    async def models(self):
        return (True, self._models, None) if self._models else (False, None, "HTTP 404")

    async def metrics(self):
        self.metrics_calls += 1
        if self._metrics_code == 501:
            return (
                False,
                '{"error":{"code":501,"message":"This server does not support metrics endpoint. Start it with `--metrics`"}}',
                "HTTP 501: not_supported_error",
            )
        return True, self._metrics_text or "", None

    async def health(self):
        return True, 200, None

    async def aclose(self):
        return None


# ---------------------------------------------------------------- TASK-04
async def test_slots_collector_ok_and_kv(settings, slots_payload):
    c = SlotsCollector(settings, FakeLlama(slots=slots_payload))
    assert await c.collect() is True
    assert c.slots_total == 6
    kv = c.kv_block()
    assert kv.used_tokens == 56414
    assert abs(kv.pct - 43.04) < 0.01
    assert kv.remaining_tokens == 74658
    assert c.processing_count() == 0
    assert c.state.stale is False


async def test_slots_collector_stale_after_failures(settings, slots_payload):
    """采集失败必须返回上一值并标 stale，且不抛异常。"""
    c = SlotsCollector(settings, FakeLlama(slots=slots_payload))
    await c.collect()
    c.client.fail_slots = True
    for _ in range(settings.stale_after_misses):
        assert await c.collect() is False
    assert c.state.stale is True
    assert c.kv_block().used_tokens == 56414  # 仍保留上一有效值
    assert c.state.last_error is not None


async def test_slots_delta_fallback_rate(settings, slots_payload):
    import copy

    payload = copy.deepcopy(slots_payload)
    c = SlotsCollector(settings, FakeLlama(slots=payload))
    await c.collect()
    payload[2]["next_token"][0]["n_decoded"] = 200
    await asyncio.sleep(0.05)
    await c.collect()
    assert c.slots_delta_tps is not None and c.slots_delta_tps > 0


# ---------------------------------------------------------------- TASK-09
async def test_metrics_skipped_when_disabled(settings):
    """endpoint_metrics=false 时不得发起请求。"""
    fake = FakeLlama(metrics_text="llamacpp:tokens_predicted_total 1\n")
    c = PrometheusCollector(settings, fake)
    c.mark_disabled("未启用")
    assert await c.collect() is False
    assert fake.metrics_calls == 0  # 一个请求都没发


async def test_metrics_501_permanent_degrade(settings):
    c = PrometheusCollector(settings, FakeLlama(metrics_code=501))
    assert await c.collect() is False
    assert c.available is False
    assert "501" in (c.disabled_reason or "")
    assert await c.collect() is False  # 第二次不再请求


async def test_metrics_ok(settings):
    text = "llamacpp:tokens_predicted_total 1198564\nllamacpp:requests_deferred 0\n"
    c = PrometheusCollector(settings, FakeLlama(metrics_text=text))
    assert await c.collect() is True
    assert c.available is True
    assert c.tokens_predicted_total() == 1198564


async def test_metrics_recovers_after_server_enables_flag(settings):
    """回归：服务端启用 --metrics 后控制台必须自行恢复，无需重启控制台。

    实测踩过：一次 501 后永久降级，运维加上 --metrics 重启 llama-server，
    界面却一直显示「未启用」。
    """
    fake = FakeLlama(metrics_code=501)
    c = PrometheusCollector(settings, fake)

    # 阶段一：服务端未启用 → 永久降级，且一个请求都不发
    c.set_endpoint_enabled(False)
    c.set_endpoint_enabled(False)
    assert await c.collect() is False
    assert c.available is False
    assert fake.metrics_calls == 0

    # 阶段二：/props 报告已启用 → 状态复位，下一拍真正去探测
    c.set_endpoint_enabled(True)
    assert c.available is None
    fake._metrics_code = 200
    fake._metrics_text = "llamacpp:tokens_predicted_total 42\n"
    assert await c.collect() is True
    assert c.available is True
    assert c.tokens_predicted_total() == 42
    assert fake.metrics_calls == 1

    # 阶段三：服务端又关掉 → 重新降级
    c.set_endpoint_enabled(False)
    assert c.available is False
    assert "未启用" in (c.disabled_reason or "")


# ---------------------------------------------------------------- TASK-06
class FakeRunner(CommandRunner):
    def __init__(self, settings, table):
        super().__init__(settings)
        self.table = table
        self.calls = []

    async def run(self, argv, timeout_s=None, label=None):
        from app.adapters.exec import CommandResult

        self.calls.append(argv)
        key = label or argv[0]
        out = self.table.get(key)
        if out is None:
            return CommandResult(
                argv=argv, returncode=1, stdout="", stderr="", duration_ms=1.0, error="not found"
            )
        return CommandResult(
            argv=argv, returncode=0, stdout=out, stderr="", duration_ms=5.0, lines=out.splitlines()
        )


async def test_gpu_collector(settings, nvidia_csv):
    from app.collectors.gpu import GpuCollector

    runner = FakeRunner(
        settings,
        {
            "nvidia-smi": nvidia_csv,
            "nvidia-smi-apps": "1261, /path/llama-server, 14590 MiB, GPU-449baa41-e0c8-16e2-37da-afe59a767ca4\n",
            "nvidia-smi-pmon": "# gpu pid type sm mem\n    0 1261 C 0 0 - -\n",
        },
    )
    c = GpuCollector(settings, runner)
    assert await c.collect() is True
    assert len(c.gpus) == 2
    assert c.vram_used_mib() == 29186
    assert c.vram_total_mib() == 32768
    assert c.max_temp_c() == 31
    assert c.gpus[0].processes[0].pid == 1261
    # 双卡必须一次查完：不允许按卡循环调用 --query-gpu
    queries = [a for a in runner.calls if any("--query-gpu=" in x for x in a)]
    assert len(queries) == 1


async def test_gpu_collector_missing_binary(settings):
    from app.collectors.gpu import GpuCollector

    c = GpuCollector(settings, FakeRunner(settings, {}))
    assert await c.collect() is False
    for _ in range(settings.stale_after_misses):
        await c.collect()
    assert c.state.stale is True


# ---------------------------------------------------------------- TASK-22/14
async def test_service_ctl_rejects_bad_action(settings):
    sc = ServiceController(settings, FakeRunner(settings, {}))
    ok, err = sc.validate_action("rm -rf /")
    assert ok is False and "not allowed" in err
    ok2, _ = sc.validate_action("restart; rm -rf /")
    assert ok2 is False
    ok3, _ = sc.validate_action("restart")
    assert ok3 is True


async def test_service_ctl_unauthorized(settings):
    table = {"sudo-check": None}  # sudo -n true 失败
    sc = ServiceController(settings, FakeRunner(settings, table))
    ok, msg, code = await sc.do_action("restart")
    assert ok is False and code == 403
    assert "sudoers" in sc.sudoers_hint


async def test_service_ctl_authorized_ok(settings):
    table = {"sudo-check": "", "systemctl-restart": ""}
    sc = ServiceController(settings, FakeRunner(settings, table))
    sc.authorized = True
    ok, msg, code = await sc.do_action("restart")
    assert ok is True and code == 202


async def test_service_ctl_busy_conflict(settings):
    sc = ServiceController(settings, FakeRunner(settings, {}))
    sc.authorized = True
    sc.busy = True
    ok, msg, code = await sc.do_action("restart")
    assert ok is False and code == 409


async def test_service_authorization_probe_uses_whitelisted_command(settings):
    """回归：最小化白名单下 ``sudo -n true`` 必然失败，探针必须用白名单内的命令。

    实测踩过：先装 sudoers 后，控制台仍报未授权，因为探针是 sudo -n true。
    """
    calls = []

    class ProbeRunner(FakeRunner):
        async def run(self, argv, timeout_s=None, label=None):
            calls.append(list(argv))
            from app.adapters.exec import CommandResult

            # 只有 reset-failed 在白名单里
            ok = argv[-1] == "reset-failed" or argv[-1] == "llm-infer.service"
            return CommandResult(
                argv=argv,
                returncode=0 if ok else 1,
                stdout="",
                stderr="" if ok else "sudo: a password is required",
                duration_ms=1.0,
            )

    sc = ServiceController(settings, ProbeRunner(settings, {}))
    assert await sc.check_authorization() is True
    assert sc.authorized is True
    assert any("reset-failed" in c for c in calls[0]), calls[0]


async def test_service_authorization_falls_back_to_general_sudo(settings):
    """白名单探针失败但存在通用 NOPASSWD 时，也应判定为已授权。"""

    class AnySudoRunner(FakeRunner):
        async def run(self, argv, timeout_s=None, label=None):
            from app.adapters.exec import CommandResult

            ok = argv[-1] == "true"  # 只有通用 sudo 可用
            return CommandResult(argv=argv, returncode=0 if ok else 1, stdout="", stderr="", duration_ms=1.0)

    sc = ServiceController(settings, AnySudoRunner(settings, {}))
    assert await sc.check_authorization() is True


async def test_service_status_parsing(settings):
    out = (
        "ActiveState=active\nSubState=running\n"
        "ExecMainStartTimestamp=Tue 2026-09-29 15:13:33 +06\nNRestarts=0\n"
    )
    sc = ServiceController(settings, FakeRunner(settings, {"systemctl-show": out}))
    st = await sc.status()
    assert st.active == "active"
    assert st.sub == "running"
    assert st.n_restarts == 0
    assert st.eta_s == settings.restart_eta_seconds


# ---------------------------------------------------------------- TASK-10
def test_history_ring_capacity(settings):
    h = History(settings)
    for i in range(settings.history_points + 50):
        h.add(MetricSnapshot(seq=i, ts=1000 + i))
    assert len(h.points) == settings.history_points
    assert h.bytes_estimate() < 1024 * 1024  # < 1 MB


def test_history_window(settings):
    import time as _t

    h = History(settings)
    now = _t.time()
    h.add(MetricSnapshot(seq=1, ts=now - 1000))
    h.add(MetricSnapshot(seq=2, ts=now - 10))
    assert len(h.window(60)) == 1


# ---------------------------------------------------------------- 基类
def test_na_helpers():
    assert to_num("[N/A]") is None
    assert to_num("") is None
    assert to_num("42") == 42.0
    assert to_int("[Not Supported]") is None
    assert to_int("7") == 7


def test_collector_state_lifecycle():
    st = CollectorState("x", stale_after=2)
    st.ok(10.0)
    assert st.stale is False and st.samples == 1
    st.fail("boom")
    assert st.stale is False
    st.fail("boom")
    assert st.stale is True
    st.ok(10.0)
    assert st.stale is False and st.last_error is None
    d = st.as_dict()
    assert d["name"] == "x" and d["errors"] == 2


# ---------------------------------------------------------------- TASK-12
async def test_ws_queue_bounded_drops_oldest(settings):
    from app.ws import _Connection

    class FakeWS:
        async def send_text(self, _):
            return None

        async def close(self, code=1000):
            return None

    conn = _Connection(FakeWS(), maxsize=3)
    for i in range(10):
        conn.offer(f"m{i}")
    assert conn.queue.qsize() == 3
    assert conn.dropped == 7
    items = [conn.queue.get_nowait() for _ in range(3)]
    assert items[-1] == "m9"  # 保留最新


async def test_ws_hub_broadcast_counts(settings):
    from app.ws import WebSocketHub

    hub = WebSocketHub(settings)
    snap = MetricSnapshot(seq=1, ts=123.0)
    assert hub.broadcast_snapshot(snap) == 0  # 无客户端时安全
    assert hub.client_count == 0
    st = hub.stats()
    assert st["metrics_clients"] == 0 and st["total_dropped"] == 0


def test_ws_payload_is_json(settings):
    from app.ws import WebSocketHub

    hub = WebSocketHub(settings)
    snap = MetricSnapshot(seq=7, ts=1.0)

    class CapturingConn:
        def __init__(self):
            self.payloads = []

        closed = False

        def offer(self, p):
            self.payloads.append(p)

    c = CapturingConn()
    hub._metrics.add(c)
    hub.broadcast_snapshot(snap)
    msg = json.loads(c.payloads[0])
    assert msg["type"] == "snapshot"
    assert msg["payload"]["seq"] == 7
    # 与 /api/overview 保持一致：字段名必须是 self 而不是 self_info
    assert "self" in msg["payload"]
    assert "self_info" not in msg["payload"]
