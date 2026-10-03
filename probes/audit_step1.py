#!/usr/bin/env python
"""第 1 步审计：硬编码探测数据 + 推理框架识别现状。

    cd "$WKL_ROOT" && ./venv/bin/python probes/audit_step1.py

检查三类问题：
  A. 页面/前端里是否存在来自某台机器的**筛选后数据**（应全部由后端运行时探测）
  B. 生产代码里是否残留"特定部署事实"（用**正则模式**判断，本文件不含真实取值）
  C. 推理框架识别现状：只认某一种框架吗？版本号从哪来？
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

#: 禁止出现在生产代码里的"特定部署事实" —— **正则模式**而非具体取值，
#: 这样守卫文件本身在开源仓库里也是干净的。
FORBIDDEN = {
    r"/home/(?!llmops\b)[A-Za-z0-9._-]+/": "开发者本机主目录路径",
    r"\b(?:10|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b": "内网私有 IP",
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b": "内网私有 IP（172.16/12）",
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b": "真实邮箱地址",
}


def strip_py(src: str) -> str:
    """剥离 Python 注释与文档字符串（否则注释里的示例会误判）。"""
    src = src.lstrip("\ufeff")
    out: list[str] = []
    in_doc = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            if s.count('"""') + s.count("'''") == 1:
                in_doc = not in_doc
            continue
        if in_doc:
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def strip_js(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())


def walk(sub: str, exts: tuple[str, ...]):
    base = os.path.join(ROOT, sub)
    if not os.path.isdir(base):
        return
    for b, _, fs in os.walk(base):
        if "__pycache__" in b:
            continue
        for f in fs:
            if f.endswith(exts):
                yield os.path.join(b, f)


def main() -> int:
    problems: list[str] = []

    print("=== A. 前端页面：是否存在硬编码的探测数据 ===")
    # 页面里的数字/型号/模型名必须是占位符，不能是具体值
    DATA_HINTS = [
        (r"V100|A100|H100|4090|MI210", "具体显卡型号"),
        (r"Xeon|EPYC|Ryzen", "具体 CPU 型号"),
        (r"580\.\d|12\.8\.2|9\.22", "具体驱动/库版本"),
        (r"llama-server|llama\.cpp", "具体推理框架名（应来自探测）"),
        (r"131072|16384|56327", "具体容量数字"),
    ]
    for name in ("index.html", "app.js", "alerts.js", "logs.js", "i18n.js"):
        p = os.path.join(ROOT, "static", name)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        code = strip_js(raw) if name.endswith(".js") else re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        for rx, why in DATA_HINTS:
            m = re.findall(rx, code)
            if m:
                hit = f"static/{name}: {why} -> {sorted(set(m))[:4]}"
                print(f"  [HARDCODED] {hit}")
                problems.append(hit)
    if not problems:
        print("  [OK] 前端无硬编码的探测数据（全部占位符/由后端下发）")

    print("\n=== B. 生产代码中的特定部署字面量 ===")
    hits_b: list[str] = []
    for p in walk("app", (".py",)):
        rel = os.path.relpath(p, ROOT)
        code = strip_py(open(p, encoding="utf-8").read())
        for pattern, why in FORBIDDEN.items():
            m = re.search(pattern, code)
            if m:
                hits_b.append(f"{rel}: 命中 {m.group(0)!r}（{why}）")
    for p in walk("static", (".js", ".html", ".css")):
        rel = os.path.relpath(p, ROOT)
        code = strip_js(open(p, encoding="utf-8").read())
        for pattern, why in FORBIDDEN.items():
            m = re.search(pattern, code)
            if m:
                hits_b.append(f"{rel}: 命中 {m.group(0)!r}（{why}）")
    for h in hits_b:
        print(f"  [FORBIDDEN] {h}")
    problems.extend(hits_b)
    if not hits_b:
        print("  [OK] 生产代码无可疑字面量")

    print("\n=== B2. 注释/文档字符串中的特定部署字面量（必清）===")
    hits_b2: list[str] = []
    for p in walk("app", (".py",)):
        rel = os.path.relpath(p, ROOT)
        for i, ln in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
            for pattern in FORBIDDEN:
                if re.search(pattern, ln):
                    hits_b2.append(f"{rel}:{i}: {ln.strip()[:88]}")
                    break
    print(f"  共 {len(hits_b2)} 行，样例（前 12 条）：")
    for h in hits_b2[:12]:
        print(f"    {h}")

    print("\n=== C. 推理框架识别现状 ===")
    from app.config import Settings
    from app.services import unitinfo

    s = Settings()
    print(f"  被监控单元        : {s.llama_unit}")
    print(f"  运行期 API 基址   : {s.llama_base_url}")
    print(f"  unit 解析器       : {unitinfo.__name__}")
    for p in walk("app", (".py",)):
        rel = os.path.relpath(p, ROOT)
        if rel.startswith("app/collectors") or "framework" in rel:
            src = open(p, encoding="utf-8").read()
            if re.search(r"ollama|vllm|sglang", src, re.I):
                print(f"  提到 ollama/vllm/sglang 的文件: {rel}")
    has_fw = os.path.exists(os.path.join(ROOT, "app", "services", "framework.py"))
    print(f"  是否已有框架识别模块 app/services/framework.py: {has_fw}")
    print("  当前硬依赖 llama.cpp 专有接口: /props /slots /metrics (llamacpp:*)")
    print("  → 换 ollama/vLLM/SGLang 时这些接口不存在，会导致大量字段为空")

    print()
    print(
        f"AUDIT_STEP1: 前端硬编码 {len(problems) - len(hits_b)} 项，生产代码禁用字面量 {len(hits_b)} 项，"
        f"待清理注释 {len(hits_b2)} 行，框架识别模块 {'已存在' if has_fw else '缺失'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
