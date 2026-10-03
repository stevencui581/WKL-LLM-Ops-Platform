"""验证「推理槽位 · KV 缓存占用」面板是否完全数据驱动。

在 目标 上执行：
    cd /home/llmops/llm-console && ./venv/bin/python probes/verify_slots_dynamic.py

做法：喂进**伪造的 /slots 响应**（不同槽位数、不同 n_ctx、不同状态），
看后端算出的 KV 块是否跟着变 —— 变了说明是自动识别，写死则不会变。
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/home/llmops/llm-console")

from app.collectors.slots import build_kv_block, parse_slots  # noqa: E402
from app.services.unitinfo import read_unit  # noqa: E402


def fake_slot(i: int, n_ctx: int, prompt: int = 0, processing: bool = False, spec: str | None = None) -> dict:
    d = {
        "id": i,
        "n_ctx": n_ctx,
        "is_processing": processing,
        "id_task": 100 + i if processing else -1,
        "n_prompt_tokens": prompt,
        "n_prompt_tokens_cache": prompt,
        "n_prompt_tokens_processed": prompt,
        "next_token": [{"n_decoded": prompt // 2}] if processing else [],
    }
    if spec is not None:
        d["params"] = {"speculative.types": spec}
    return d


def show(title: str, payload: list[dict], total_ctx: int) -> None:
    slots = parse_slots(payload)
    kv = build_kv_block(slots, total_ctx)
    print(f"\n--- {title} ---")
    print(f"  输入槽位数      : {len(payload)}")
    print(f"  后端解析槽位数  : {len(slots)}")
    print(f"  槽位 id 列表    : {[s.id for s in slots]}")
    print(f"  各槽 n_ctx      : {[s.n_ctx for s in slots]}")
    print(f"  KV 已用 tokens  : {kv.used_tokens}")
    print(f"  KV 总容量       : {kv.total_tokens}")
    pct = f"{kv.pct:.2f}%" if kv.pct is not None else "—"
    print(f"  KV 占用率       : {pct}")
    print(f"  剩余 tokens     : {kv.remaining_tokens}")
    print(f"  状态            : {[s.state for s in slots]}")


def main() -> int:
    print("=" * 68)
    print("一、后端是否数据驱动（喂伪造数据，看输出是否跟着变）")
    print("=" * 68)

    # 场景 1：本机真实形态（6 槽, -kvu 统一池 → 每槽 n_ctx 都等于总容量）
    show("场景1：6 槽 · unified（每槽 n_ctx=131072）", [fake_slot(i, 131072, 0) for i in range(6)], 131072)

    # 场景 2：只有 3 个槽（如 --parallel 3）
    show("场景2：3 槽 · n_ctx=32768", [fake_slot(i, 32768, 100) for i in range(3)], 32768)

    # 场景 3：8 个槽（如 --parallel 8）
    show("场景3：8 槽 · n_ctx=65536", [fake_slot(i, 65536, 500) for i in range(8)], 65536)

    # 场景 4：单槽（--parallel 1）
    show("场景4：1 槽 · n_ctx=4096", [fake_slot(0, 4096, 2048)], 4096)

    # 场景 5：槽位 id 不连续 / 不从 0 开始
    show(
        "场景5：id 为 7,9,11（不连续、不从 0 开始）",
        [fake_slot(7, 8192, 10), fake_slot(9, 8192, 20), fake_slot(11, 8192, 30)],
        8192,
    )

    # 场景 6：**非 unified**（未加 -kvu）→ 每槽 n_ctx = 总容量 / 槽数
    nonuni = [fake_slot(i, 131072 // 6, 0) for i in range(6)]
    show("场景6：6 槽 · 非 unified（每槽 n_ctx=21845）", nonuni, 21845)

    print()
    print("=" * 68)
    print("二、本机真实 /slots（对照）")
    print("=" * 68)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/slots", timeout=5) as r:
            real = json.load(r)
        print(f"  真实槽位数      : {len(real)}")
        print(f"  各槽 n_ctx      : {[s.get('n_ctx') for s in real]}")
        print(f"  各槽 id         : {[s.get('id') for s in real]}")
        specs = [(s.get("params") or {}).get("speculative.types") for s in real]
        print(f"  各槽 spec.types : {specs}")
    except Exception as exc:  # noqa: BLE001
        print(f"  取 /slots 失败: {exc}")

    print()
    print("=" * 68)
    print("三、启动参数是否自动识别（决定面板文案与 KV 分母）")
    print("=" * 68)
    cfg = read_unit("llm-infer.service")
    print(f"  unit 文件解析   : {'成功' if cfg.raw_exec else '失败'}")
    print(f"  --parallel      : {cfg.parallel or '（未解析到）'}")
    print(f"  -c / --ctx-size : {cfg.n_ctx or '（未解析到）'}")
    print(
        f"  -sm / split     : {cfg.split_mode if hasattr(cfg, 'split_mode') else '（UnitConfig 暂无该字段）'}"
    )
    print(f"  -ts / tensor    : {cfg.tensor_split or '（未解析到）'}")
    print(f"  --spec-type     : {cfg.spec_type or '（未解析到）'}")
    print(f"  --metrics       : {cfg.metrics_flag}")
    print(f"  -kvu 是否解析到 : {'是' if hasattr(cfg, 'kv_unified') else '否 —— UnitConfig 尚未采集该参数'}")

    print()
    print("=" * 68)
    print("四、面板文案中的写死项扫描")
    print("=" * 68)
    import re

    html = open("/home/llmops/llm-console/static/index.html", encoding="utf-8").read()
    js = open("/home/llmops/llm-console/static/app.js", encoding="utf-8").read()
    checks = [
        ("index.html 含「-kvu 统一池」静态文字", "-kvu 统一池" in html),
        ("app.js 含「-kvu 统一池」硬编码拼接", "-kvu 统一池" in js),
        ("app.js 含 `|| 6` 槽位兜底", bool(re.search(r"slots_total \|\| 6", js))),
        ("app.js 槽位行是 forEach 动态生成", "slotList.forEach" in js),
        ("app.js 槽位表先清空再渲染", "tb.innerHTML = ''" in js),
        ("「来源」列取不到时显示未知", "s.source ? s.source" in js),
    ]
    for label, hit in checks:
        mark = "命中" if hit else "未命中"
        print(f"  [{mark}] {label}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
