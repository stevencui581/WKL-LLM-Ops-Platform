#!/usr/bin/env python
"""8 个缺陷的修复现状审计（v0.4.4 前置）。

    cd /home/llmops/llm-console && ./venv/bin/python probes/audit_defects.py

对每个缺陷逐项核对「修复代码是否在位 + 守卫测试是否存在」，
输出一张台账，作为 v0.4.4 的工作基线。
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

rows: list[tuple[str, str, bool, str]] = []

#: 只上行、不回传的目录（文档在本地编写，服务器只是镜像）
UPLOAD_ONLY_DIRS = {"docs"}


def src(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read()


def code_of(rel: str) -> str:
    """只取**可执行代码**（剥离注释与三引号块）。

    **这是本审计脚本第一版出错的根因**：直接用 ``find("if not fields:")``
    命中了注释里的示例文字，把已经修好的 D1 误判为"未修复"。
    源码扫描必须先剥离注释 —— 与 D5（BOM 让扫描失效）是同一类失败模式。
    """
    text = src(rel).lstrip("\ufeff")
    out: list[str] = []
    in_doc = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            marks = s.count('"""') + s.count("'''")
            if marks == 1:
                in_doc = not in_doc
            continue
        if in_doc:
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


#: 粘连损坏的真实形态：``#`` 注释之后**又出现字段定义**
GLUED = re.compile(r"#.*\S+\s*:\s*[A-Za-z_][\w\[\]|. ]*\s*=")


def mark(did: str, name: str, ok: bool, detail: str) -> None:
    rows.append((did, name, ok, detail))
    print(f"  [{'FIXED' if ok else 'MISSING'}] {did} {name} — {detail}")


def main() -> int:
    tests = (
        "".join(src(f"tests/{f}") for f in os.listdir(os.path.join(ROOT, "tests")) if f.endswith(".py"))
        if os.path.isdir(os.path.join(ROOT, "tests"))
        else ""
    )

    print("=== 缺陷修复现状审计 ===\n")

    # ---- 1. CLIENT_CANCEL 从未生效 ----
    ls = code_of("app/services/log_stats.py")
    lines = ls.splitlines()

    def first_line(needle: str) -> int:
        for i, ln in enumerate(lines):
            if needle in ln:
                return i
        return -1

    cancel_pos = first_line('"cancel task" in text')
    early = first_line("if not fields:")
    ok1 = 0 <= cancel_pos < early
    mark(
        "D1",
        "CLIENT_CANCEL 告警从未生效",
        ok1 and "test_d1_cancel_detection_precedes_early_return" in tests,
        f"取消检测第 {cancel_pos + 1} 行 < 早退第 {early + 1} 行（仅比对可执行代码）；"
        f"守卫测试{'存在' if 'test_d1_cancel_detection_precedes_early_return' in tests else '缺失'}",
    )

    # ---- 2. 事件型告警永不恢复 ----
    cfg = code_of("app/config.py")
    al = code_of("app/services/alerts.py")
    ok2 = (
        "event_alert_ttl_s" in cfg
        and "event_alert_ttl_s" in al
        and "clear_event(code)" in al
        and "test_d2_ttl_configured_and_enforced" in tests
    )
    mark("D2", "事件型告警永不恢复", ok2, "event_alert_ttl_s 配置 + evaluate 超时清除 + note_* 刷新窗口")

    # ---- 3. 历史日志「选 30 天只覆盖 1 天」 ----
    hist = code_of("app/collectors/history.py")
    route = code_of("app/routes/history.py")
    ok3 = ("(days, limit)" in hist or "(d, lim)" in hist) and "_evict" in hist
    ok3b = "log_history_default_limit" in hist and "Query(2000" not in route
    ok3c = "test_d3_cache_key_includes_limit" in tests
    mark(
        "D3",
        "历史日志选 30 天只覆盖 1 天",
        ok3 and ok3b and ok3c,
        f"缓存键含 limit={ok3}；路由未写死默认值={ok3b}；守卫测试={ok3c}",
    )

    # ---- 4. spec_types 字段粘连损坏 ----
    models = code_of("app/models.py")
    ok4 = bool(re.search(r"^\s*spec_types:\s*str\s*=", models, re.M))
    # 精确判据：注释之后又出现字段定义（函数签名的多参数是正常的，不算）
    glued = []
    for base, _, files in os.walk(os.path.join(ROOT, "app")):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            with open(p, encoding="utf-8") as fh:
                for i, ln in enumerate(fh, 1):
                    if GLUED.search(ln) and "noqa" not in ln and "type: ignore" not in ln:
                        glued.append(f"{f}:{i}")
    mark(
        "D4",
        "spec_types 字段被字符串替换粘连",
        ok4 and not glued,
        f"字段在位={ok4}；粘连扫描={glued or '无'}",
    )

    # ---- 5. UTF-8 BOM ----
    bad_bom = []
    pats = ("app", "tests", "probes", "deploy", "static", "docs", "tools")
    for pat in pats:
        base = os.path.join(ROOT, pat)
        if not os.path.isdir(base):
            continue
        for b, _, fs in os.walk(base):
            for f in fs:
                if not f.endswith((".py", ".js", ".css", ".html", ".md", ".sh")):
                    continue
                p = os.path.join(b, f)
                with open(p, "rb") as fh:
                    if fh.read(3) == b"\xef\xbb\xbf":
                        bad_bom.append(os.path.relpath(p, ROOT))
    for f in os.listdir(ROOT):
        if f.endswith(".sh"):
            with open(os.path.join(ROOT, f), "rb") as fh:
                if fh.read(3) == b"\xef\xbb\xbf":
                    bad_bom.append(f)
    ok5 = not bad_bom and "test_d5_no_bom_anywhere" in tests
    mark(
        "D5",
        "PowerShell 写入 UTF-8 BOM",
        ok5,
        f"带 BOM 文件={bad_bom or '无'}；守卫测试={'存在' if 'test_d5_no_bom_anywhere' in tests else '缺失'}",
    )

    # ---- 6. KV 量化重复标注「（默认）」 ----
    props = code_of("app/collectors/props.py")
    ok6 = (
        '"key": "kv_quant", "value": kv_raw' in props
        and "kv_label, kv_source, kv_raw = self._kv_quant" in props
    )
    ok6b = "test_d6_badge_value_is_raw" in tests
    mark("D6", "KV 量化重复标注「（默认）」", ok6 and ok6b, f"badge_items 用裸值={ok6}；守卫测试={ok6b}")

    # ---- 7. 历史缓存无界增长 ----
    ok7 = "def _evict" in hist and "test_d7_cache_eviction_works" in tests
    mark(
        "D7",
        "历史缓存无界增长",
        ok7,
        f"_evict 存在={'def _evict' in hist}；守卫测试={'test_d7_cache_eviction_works' in tests}",
    )

    # ---- 8. 文档生成器给中文插零宽空格 ----
    mdtext_path = os.path.join(ROOT, "tools", "mdtext.py")
    md2 = src("tools/md2docx.py")
    has_mdtext = os.path.exists(mdtext_path)
    ok8 = (
        has_mdtext
        and "from mdtext import" in md2
        and "def brk" not in md2
        and "test_d8_brk_only_ascii_tokens" in tests
    )
    mark(
        "D8",
        "文档生成器给中文插零宽空格",
        ok8,
        f"mdtext.py 存在={has_mdtext}；md2docx 复用={('from mdtext import' in md2)}；"
        f"守卫测试={'test_d8_brk_only_ascii_tokens' in tests}",
    )

    # ---- 9. 本地与远端静默分叉（v0.4.4 做审计时新发现） ----
    up_m = re.search(r"INCLUDE_DIRS\s*=\s*\(([^)]*)\)", src("deploy/upload.py"))
    sy_m = re.search(r"DIRS\s*=\s*\(([^)]*)\)", src("deploy/sync_from_host.py"))
    up_d = set(re.findall(r'"([^"]+)"', up_m.group(1))) if up_m else set()
    sy_d = set(re.findall(r'"([^"]+)"', sy_m.group(1))) if sy_m else set()
    gap = sorted(up_d - sy_d - UPLOAD_ONLY_DIRS)
    ok9 = not gap and "test_d9_sync_dirs_match_upload_dirs" in tests
    mark(
        "D9",
        "本地与远端静默分叉（sync 漏目录）",
        ok9,
        f"代码目录缺口={gap or '无'}；守卫测试={'test_d9_sync_dirs_match_upload_dirs' in tests}",
    )

    fixed = sum(1 for _, _, ok, _ in rows if ok)
    print(f"\n=== 台账：{fixed}/{len(rows)} 项修复在位 ===")
    for did, name, ok, _ in rows:
        print(f"  {'✓' if ok else '✗'} {did} {name}")
    print("\nAUDIT_OK" if fixed == len(rows) else f"\nAUDIT_INCOMPLETE: {len(rows) - fixed} 项待处理")
    return 0 if fixed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
