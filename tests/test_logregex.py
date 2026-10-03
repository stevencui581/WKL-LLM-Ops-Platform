"""日志解析回归测试（方案 TASK-08 验收标准）。

对应任务验收：
  * 9 个正则在 253 真实日志上命中率 100%，无误匹配；
  * draft acceptance 行解析出 rate/accepted/generated/mean_len；
  * 行首壁钟时间被正确解析，而 2990.36.159.181 不被当作时间戳；
  * 解析函数永不抛异常。
"""

from __future__ import annotations

from app.collectors.logregex import (
    RE_LOADED,
    parse_acceptance,
    parse_all,
    parse_eval,
    parse_exit,
    parse_journal_line,
    parse_lcp,
    parse_prefill,
    parse_progress,
    parse_release,
    parse_total_time,
)

LOG_TS_LINE = (
    "2026-10-01T17:04:10+06:00 llm-host llama-server[1261]: "
    "2990.36.159.181 I slot print_timing: id  2 | task 10637 | "
    "draft acceptance = 0.81783 (  422 accepted /   516 generated), mean len =  2.64"
)


def test_prefix_parsed_as_wallclock():
    ln = parse_journal_line(LOG_TS_LINE)
    assert ln.ts == "2026-10-01T17:04:10+06:00"
    assert ln.epoch > 0
    assert ln.level == "I"
    assert ln.slot == 2
    assert ln.task == 10637
    # 关键：行内的运行时长度绝不能被当成时间戳
    assert "2990.36.159.181" in ln.text
    assert "2990" not in ln.ts


def test_runtime_counter_is_not_ip_or_time():
    """2990.36.159.181 看似 IP，其实是「运行分钟.秒.毫秒.微秒」。"""
    ln = parse_journal_line(LOG_TS_LINE)
    assert not ln.ts.startswith("2990")
    assert ln.epoch > 1_700_000_000  # 2023 之后，证明是真实壁钟时间


def test_acceptance_regex():
    a = parse_acceptance(LOG_TS_LINE)
    assert a is not None
    assert a["accepted"] == 422
    assert a["generated"] == 516
    assert a["mean_len"] == 2.64
    assert abs(a["ratio"] - 422 / 516) < 1e-9
    assert abs(a["ratio"] - 0.81783) < 1e-4


def test_eval_prefill_and_total_time(journal_lines):
    joined = "\n".join(journal_lines)
    ev = parse_eval(joined)
    assert ev is not None
    assert ev["tokens"] == 679  # 不能匹配到 prompt eval time 的 65
    assert ev["tps"] == 68.22

    pf = parse_prefill(joined)
    assert pf is not None
    assert pf["tokens"] == 65
    assert pf["tps"] == 56.23

    tt = parse_total_time(joined)
    assert tt is not None and tt["tokens"] == 744


def test_eval_does_not_match_prompt_eval(journal_lines):
    """回归：RE_EVAL 必须排除 prompt eval time，否则生成速率会被预填充速率污染。"""
    prefill_line = [ln for ln in journal_lines if "prompt eval time" in ln][0]
    assert parse_prefill(prefill_line)["tps"] == 56.23
    assert parse_eval(prefill_line) is None
    gen_line = [ln for ln in journal_lines if "|        eval time" in ln][0]
    assert parse_eval(gen_line)["tps"] == 68.22


def test_progress_regex(journal_lines):
    """逐行解析：样本里有两行进度日志，取值应分别正确。"""
    vals = [parse_progress(ln) for ln in journal_lines]
    vals = [v for v in vals if v]
    assert len(vals) == 2
    assert vals[0]["n_gen"] == 413 and vals[0]["tg_3s"] == 66.09
    assert vals[1]["n_gen"] == 614 and vals[1]["tg"] == 67.86


def test_release_truncated(journal_lines):
    r = parse_release("stop processing: n_tokens = 56414, truncated = 0")
    assert r == {"n_tokens": 56414, "truncated": 0}
    r2 = parse_release("stop processing: n_tokens = 130900, truncated = 1")
    assert r2["truncated"] == 1


def test_lcp_regex(journal_lines):
    lcp = parse_lcp("\n".join(journal_lines))
    assert lcp is not None
    assert lcp["f_sim_best"] == 0.998


def test_exit_and_loaded(journal_lines):
    ex = parse_exit("srv run: instance name=qwen3.8-27B exited with status 0")
    assert ex == {"status": 0}
    assert RE_LOADED.search("srv  llama_server: model loaded")


def test_all_fields_on_real_sample(journal_lines):
    """在整个真实样本上跑一遍：命中率 100% 且不抛异常。"""
    hits = {
        "acceptance": 0,
        "eval": 0,
        "prefill": 0,
        "progress": 0,
        "release": 0,
        "lcp": 0,
        "total_time": 0,
        "exit": 0,
    }
    for line in journal_lines:
        fields = parse_all(line)
        for k in list(hits):
            if k in fields:
                hits[k] += 1
    assert hits["acceptance"] == 1
    assert hits["eval"] == 1
    assert hits["prefill"] == 1
    assert hits["progress"] == 2
    assert hits["release"] == 3
    assert hits["lcp"] == 1
    assert hits["total_time"] == 1
    assert hits["exit"] == 1


def test_parser_never_raises():
    """解析函数必须永不抛异常——跟随循环里任何异常都会终止采集。"""
    weird = [
        "",
        "   ",
        "not a log line at all",
        "\x00\x01\x02",
        "2026-10-01T17:04:10+06:00",
        "2026-10-01T17:04:10+06:00 host ident: ",
        "draft acceptance = ",
        "draft acceptance = abc (x accepted / y generated), mean len = z",
        "eval time = NaN ms / tokens ( ms per token, tokens per second)",
        "2990.36.159.181 I slot print_timing: id  2 | task -1 | n_gen = 0, tg = 0.0 t/s, tg_3s = 0.0 t/s",
        "🚀" * 50,
    ]
    for w in weird:
        ln = parse_journal_line(w)
        assert ln is not None
        parse_all(w)  # 不得抛异常


def test_highlight_tags(journal_lines):
    tags = {}
    for line in journal_lines:
        ln = parse_journal_line(line)
        if ln.highlight:
            tags[ln.highlight] = tags.get(ln.highlight, 0) + 1
    assert tags.get("exit", 0) >= 1
    assert tags.get("truncated", 0) >= 1
    assert tags.get("cancel", 0) >= 1
    assert tags.get("loaded", 0) >= 1


def test_levels_parsed(journal_lines):
    levels = [parse_journal_line(ln).level for ln in journal_lines]
    assert "W" in levels  # cancel task 行
    assert levels.count("I") >= 10
