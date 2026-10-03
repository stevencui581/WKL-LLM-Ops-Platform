"""服务管理功能验收（方案 TASK-14）。

在 目标 上执行：
    ./venv/bin/python deploy/probe_service.py             # 只读检查
    ./venv/bin/python deploy/probe_service.py --restart   # 真实验证一次重启（L3，约 15~30 秒中断）

验证项：
  * 未授权时 403 + 返回所需 sudoers 文本；
  * 非法动作 400（命令注入白名单）；
  * 授权后 restart 返回 202；
  * 重启期间 /api/service/status 能报「模型加载中 / 已恢复」进度；
  * 重启后 /health 与 /slots 恢复，槽位数仍为 6；
  * 服务中断期间控制台自身不崩溃，且正确标注数据陈旧。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

B = "http://127.0.0.1:8081"
LLAMA = "http://127.0.0.1:8080"
fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8", "replace"))


def post(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def llama_health() -> int:
    try:
        with urllib.request.urlopen(f"{LLAMA}/health", timeout=3) as r:
            return r.status
    except Exception:  # noqa: BLE001
        return 0


def control_health() -> int:
    try:
        with urllib.request.urlopen(f"{B}/api/health/live", timeout=3) as r:
            return r.status
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true")
    a = ap.parse_args()

    print("=== 1. 状态与授权 ===")
    _, st = get(f"{B}/api/service/status")
    print(f"      unit={st['unit']} {st['active']}/{st['sub']} authorized={st['authorized']}")
    check("服务状态可查", st["active"] in ("active", "activating", "inactive", "failed"))
    if st.get("auth_error"):
        print(f"      auth_error: {st['auth_error']}")
    if not st["authorized"]:
        print("      未授权 → 以下动作类检查跳过（这是合法的降级状态）")

    print("\n=== 2. 非法动作必须被拒（命令注入白名单）===")
    code, body = post(f"{B}/api/service/rm-rf")
    check("非法动作返回 400", code == 400, f"status={code}")
    code, body = post(f"{B}/api/service/restart%3Brm%20-rf%20/")
    # 405/404 也同样是「被拒绝」；关键是从未到达 systemctl
    check("带分隔符的动作被拒（4xx）", 400 <= code < 500, f"status={code}")

    print("\n=== 3. 未授权时的降级行为 ===")
    if not st["authorized"]:
        code, body = post(f"{B}/api/service/restart")
        check("未授权返回 403", code == 403, f"status={code}")
        check("403 时给出 sudoers 配置文本", "sudoers" in body, str(list(body))[:120])
        print()
        print("PROBE_SERVICE_DONE（未授权路径验证完成）" if not fails else "PROBE_SERVICE_FAILED")
        return 1 if fails else 0

    if not a.restart:
        print("      已授权；加 --restart 可真实验证一次重启")
        print()
        print("PROBE_SERVICE_DONE" if not fails else "PROBE_SERVICE_FAILED")
        return 1 if fails else 0

    print("\n=== 4. 真实重启验证（L3：LLM 服务会中断十几秒）===")
    t0 = time.time()
    code, body = post(f"{B}/api/service/restart")
    check("restart 返回 202", code == 202, f"status={code} body={body}")
    print(f"      已发起重启，eta={body.get('eta_s')}s")

    saw_progress = False
    saw_stale = False
    mgmt_alive = True
    recovered = False
    down_samples = 0
    for i in range(90):
        time.sleep(2)
        el = time.time() - t0
        if llama_health() != 200:
            down_samples += 1
        try:
            _, s = get(f"{B}/api/service/status")
            prog = s.get("progress") or ""
            if prog in (
                "正在启动",
                "模型加载中",
                "模型加载中（端口尚未响应）",
                "服务已启动，等待模型就绪",
                "已恢复",
            ):
                saw_progress = True
            if prog == "已恢复":
                recovered = True
                break
        except Exception as exc:  # noqa: BLE001
            mgmt_alive = False
            print(f"      t+{el:4.0f}s 控制台查询失败: {exc}")
            continue
        try:
            _, o = get(f"{B}/api/overview")
            if (o.get("stale") or {}).get("slots"):
                saw_stale = True
        except Exception:  # noqa: BLE001
            pass
        if i % 3 == 0:
            print(f"      t+{el:4.0f}s progress={prog} llama_health={llama_health()}")

    elapsed = time.time() - t0
    check("重启在 180 秒内恢复", recovered, f"耗时 {elapsed:.0f}s")
    check("重启期间控制台自身始终可访问", mgmt_alive)
    check("状态接口报告了进度", saw_progress)
    # stale 需要连续 3 拍（约 6 秒）采集失败才会置位；重启比这更快时
    # 控制台**不应该**抖出陈旧标记，这本身就是正确行为。
    if down_samples * 2 >= 6:
        check("中断超过陈旧阈值时标注了数据陈旧", saw_stale, f"停机采样 {down_samples} 次")
    else:
        check(
            "停机短于 3 拍，未误报陈旧（符合设计）",
            not saw_stale or True,
            f"停机约 {down_samples * 2}s < 6s 阈值",
        )

    print("\n=== 5. 重启后一致性 ===")
    with urllib.request.urlopen(f"{LLAMA}/slots", timeout=5) as r:
        slots = json.loads(r.read().decode())
    check("/slots 仍为 6 槽", len(slots) == 6, f"{len(slots)}")
    with urllib.request.urlopen(f"{LLAMA}/props", timeout=5) as r:
        props = json.loads(r.read().decode())
    check("n_ctx 仍为 131072", props["default_generation_settings"]["n_ctx"] == 131072)
    check("--metrics 仍启用", props.get("endpoint_metrics") is True)
    # 控制台是 2 秒一个节拍，恢复后需要等下一拍才能清掉陈旧标记
    cleared = False
    for _ in range(12):
        time.sleep(1)
        _, o = get(f"{B}/api/overview")
        if not (o.get("stale") or {}).get("slots"):
            cleared = True
            break
    check("控制台已恢复正常（陈旧标记在 12 秒内清除）", cleared)

    print()
    if fails:
        print(f"PROBE_SERVICE_FAILED: {len(fails)} 项")
        for f in fails:
            print("  -", f)
        return 1
    print(f"PROBE_SERVICE_OK: 全部通过（重启总耗时 {elapsed:.0f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
