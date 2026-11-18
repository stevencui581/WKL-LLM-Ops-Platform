"""journald 跟随器测试（方案 TASK-08 验收标准）。

覆盖：
  * 游标文件存在/不存在时的命令行参数（首次回填 -n）；
  * backfill() 用真实样本种子填充，且空闲服务器上日志面板也有内容；
  * 环形缓冲、订阅/退订、队列有界丢旧；
  * 解析失败不中断采集。
"""

from __future__ import annotations

import asyncio

import pytest

from app.collectors.journal import JournalFollower


class FakeStream:
    def __init__(self, data: bytes):
        self._lines = data.splitlines(keepends=True)
        self._i = 0

    async def readline(self) -> bytes:
        if self._i >= len(self._lines):
            return b""
        ln = self._lines[self._i]
        self._i += 1
        return ln


class FakeJProc:
    def __init__(self, data: bytes, rc: int = 0):
        self.stdout = FakeStream(data)
        self.stderr = FakeStream(b"")
        self.returncode = rc

    async def communicate(self):
        return b"".join(self.stdout._lines), b""

    def terminate(self):
        self.returncode = -15

    async def wait(self):
        return self.returncode


def test_build_argv_without_cursor_adds_backfill(settings):
    f = JournalFollower(settings)
    argv = f.build_argv()
    assert "--cursor-file" in argv
    assert "-n" in argv and str(settings.journal_backfill_lines) in argv
    assert "--since" in argv


def test_build_argv_with_cursor_has_no_backfill(settings, tmp_path):
    import os

    os.makedirs(settings.state_dir, exist_ok=True)
    with open(settings.journal_cursor_path, "w") as fh:
        fh.write("s=abc;i=1;b=1")
    f = JournalFollower(settings)
    argv = f.build_argv()
    assert "-n" not in argv
    assert "--since" not in argv


async def test_backfill_seeds_ring_from_real_sample(settings, journal_lines, monkeypatch):
    data = ("\n".join(journal_lines) + "\n").encode("utf-8")
    calls = []

    async def fake_exec(*argv, **kw):
        calls.append(argv)
        return FakeJProc(data)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    f = JournalFollower(settings)
    n = await f.backfill(40)
    assert n == len(journal_lines)
    assert len(f.ring) == len(journal_lines)
    assert f.lines_total == len(journal_lines)
    # 结构化统计也一并被填充 —— 空闲服务器上 MTP 卡片不会空着
    assert f.stats.mtp_accept is not None
    assert abs(f.stats.mtp_accept - 422 / 516) < 1e-9
    assert f.stats.draft_mean_len == 2.64
    assert f.stats.prefill_tps == 56.23
    # 不带游标的一次性查询
    assert "--cursor-file" not in calls[0]


async def test_backfill_survives_missing_journalctl(settings, monkeypatch):
    async def boom(*a, **k):
        raise FileNotFoundError("journalctl")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    f = JournalFollower(settings)
    assert await f.backfill() == 0
    assert len(f.ring) == 0


async def test_backfill_never_raises_on_garbage(settings, monkeypatch):
    data = b"\xff\xfe not a log line\n\n\x00\x01\n"

    async def fake_exec(*argv, **kw):
        return FakeJProc(data)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    f = JournalFollower(settings)
    n = await f.backfill(10)
    assert n == 2  # 空行被跳过，乱码行不抛异常


async def test_ring_is_bounded(settings, journal_lines, monkeypatch):
    settings.log_ring_max = 5
    data = ("\n".join(journal_lines) + "\n").encode("utf-8")

    async def fake_exec(*argv, **kw):
        return FakeJProc(data)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    f = JournalFollower(settings)
    await f.backfill(40)
    assert len(f.ring) == 5  # 环形缓冲上限生效


async def test_publish_drops_oldest_when_full(settings):
    f = JournalFollower(settings)
    q = f.subscribe(maxsize=2)
    from app.models import LogLine

    for i in range(5):
        f._publish(LogLine(text=f"line{i}", ts=""))
    assert q.qsize() == 2
    assert q.get_nowait().text == "line3"  # 丢最旧，保留最新
    f.unsubscribe(q)
    assert q not in f._subscribers


async def test_subscribe_unsubscribe(settings):
    f = JournalFollower(settings)
    q = f.subscribe()
    assert q in f._subscribers
    f.unsubscribe(q)
    assert q not in f._subscribers


def test_recent_returns_tail(settings, journal_lines, monkeypatch):
    f = JournalFollower(settings)
    from app.models import LogLine

    for i in range(10):
        f.ring.append(LogLine(text=f"l{i}", ts=""))
    tail = f.recent(3)
    assert [x.text for x in tail] == ["l7", "l8", "l9"]


async def test_start_calls_backfill_then_follows(settings, monkeypatch):
    """start() 必须先种子回填，再启动跟随任务。"""
    order = []

    async def fake_backfill(self, lines=None):
        order.append("backfill")
        return 1

    class NeverEnding:
        async def readline(self):
            await asyncio.sleep(3600)
            return b""

    async def fake_exec(*argv, **kw):
        order.append("follow")
        # _run() 现在会先查单元状态，这一步也必须能正常返回
        if argv and str(argv[0]).endswith("systemctl"):
            return FakeJProc(b"loaded\n")
        p = FakeJProc(b"")
        p.stdout = NeverEnding()
        return p

    monkeypatch.setattr(JournalFollower, "backfill", fake_backfill)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    f = JournalFollower(settings)
    await f.start()
    await asyncio.sleep(0.05)
    await f.stop()
    assert order[0] == "backfill"
    assert "follow" in order
    assert f._task is None


# ===========================================================================
# v0.6.1：单元不存在 / journalctl 立刻退出时不得 1 秒重启一次
# ===========================================================================
async def test_unit_load_state_parses_not_found(settings, monkeypatch):
    async def fake_exec(*argv, **kw):
        return FakeJProc(b"not-found\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    f = JournalFollower(settings)
    assert await f.unit_load_state() == "not-found"


async def test_unit_load_state_unknown_when_systemctl_missing(settings, monkeypatch):
    async def boom(*a, **k):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    f = JournalFollower(settings)
    assert await f.unit_load_state() == "unknown"


async def test_run_marks_actionable_reason_when_unit_missing(settings, monkeypatch):
    """单元不存在时：给出「检查 LLMCONSOLE_LLAMA_UNIT」的原因，而不是空转。"""

    async def fake_state(self):
        return "not-found"

    async def stop_after_first_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(JournalFollower, "unit_load_state", fake_state)
    monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)
    f = JournalFollower(settings)
    with pytest.raises(asyncio.CancelledError):
        await f._run()
    reason = f.unavailable_reason or ""
    assert "不存在" in reason
    assert "LLMCONSOLE_LLAMA_UNIT" in reason
    assert f.restarts == 0, "单元不存在不应计入重启次数"


async def test_quick_exit_backoff_and_reason(settings, monkeypatch):
    """journalctl 立刻退出且零输出：指数退避 + 三次后给出原因。"""
    sleeps: list[float] = []

    async def fake_state(self):
        return "loaded"

    async def fake_follow(self):
        return 0  # 一行都没有 → 视为异常退出

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(JournalFollower, "unit_load_state", fake_state)
    monkeypatch.setattr(JournalFollower, "_follow_once", fake_follow)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    f = JournalFollower(settings)
    with pytest.raises(asyncio.CancelledError):
        await f._run()
    assert sleeps[:3] == [1.0, 2.0, 4.0], f"退避序列不对：{sleeps}"
    assert "反复退出" in (f.unavailable_reason or "")
