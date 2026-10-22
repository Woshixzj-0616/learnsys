"""Golden set 重放：改提示词 / 换模型前后，用同一批任务对比正确性与速度。

用法：
    python tools/golden_run.py --out docs/golden/结果-20261022.json
    python tools/golden_run.py --limit 5                # 先跑 5 条试水
    python tools/golden_run.py --compare 旧.json 新.json # 对比两份结果

任务在 `docs/golden/tasks.jsonl`；判据是关键词（must_all / must_any / must_not），
不是标准答案。`manual=true` 的任务只记录，不计入自动通过率 —— 需要人看一眼。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_TASKS = ROOT / "docs" / "golden" / "tasks.jsonl"
BASE = "http://127.0.0.1:8765"


def load_tasks(path: pathlib.Path) -> list[dict]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    return tasks


def judge(task: dict, answer: str) -> list[str]:
    """返回不满足的判据；空列表 = 通过。"""
    text = str(answer or "")
    issues: list[str] = []
    missing_all = [word for word in task.get("must_all") or [] if word not in text]
    if missing_all:
        issues.append("缺少：" + "、".join(missing_all))
    any_words = task.get("must_any") or []
    if any_words and not any(word in text for word in any_words):
        issues.append("一个都没出现：" + "、".join(any_words))
    hit_forbidden = [word for word in task.get("must_not") or [] if word in text]
    if hit_forbidden:
        issues.append("不该出现：" + "、".join(hit_forbidden))
    return issues


def _health() -> dict:
    with urllib.request.urlopen(f"{BASE}/api/health", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def ask(prompt: str, token: str, timeout: float = 120.0) -> dict:
    body = json.dumps({
        "message": prompt, "module": "golden", "internal": True,
        "mode": "explain",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE}/api/agent/chat", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Learnsys-Token": token})
    started = time.monotonic()
    first_ms = 0
    text = ""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            kind = event.get("kind")
            if kind in ("text", "thinking") and not first_ms:
                first_ms = int((time.monotonic() - started) * 1000)
            if kind == "text":
                text += event.get("text") or ""
            elif kind == "done":
                text = (event.get("data") or {}).get("text") or text
            elif kind == "error":
                text = event.get("text") or "（模型报错）"
    return {"text": text.strip(), "first_ms": first_ms,
            "total_ms": int((time.monotonic() - started) * 1000)}


def run(tasks: list[dict], out: pathlib.Path, limit: int = 0) -> int:
    health = _health()
    token = health["token"]
    picked = tasks[:limit] if limit else tasks
    rows = []
    for index, task in enumerate(picked, 1):
        print(f"[{index}/{len(picked)}] {task['id']}", flush=True)
        result = ask(task["prompt"], token)
        issues = judge(task, result["text"])
        ok = not issues
        rows.append({
            "id": task["id"], "category": task.get("category", ""),
            "prompt": task["prompt"], "manual": bool(task.get("manual")),
            "ok": ok, "issues": issues, **result,
        })
        mark = "通过" if ok else "未过"
        print(f"    {mark} · 首 token {result['first_ms']}ms · "
              f"总 {result['total_ms']}ms", flush=True)
    auto = [row for row in rows if not row["manual"]]
    summary = {
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": health.get("model", ""),
        "total": len(rows),
        "auto_total": len(auto),
        "auto_pass": sum(1 for row in auto if row["ok"]),
        "manual_total": len(rows) - len(auto),
        "first_ms_p95": _p95([row["first_ms"] for row in rows]),
        "total_ms_p95": _p95([row["total_ms"] for row in rows]),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n自动通过 {summary['auto_pass']}/{summary['auto_total']}；"
          f"人工复核 {summary['manual_total']} 条；结果 → {out}")
    return 0 if summary["auto_pass"] == summary["auto_total"] else 1


def _p95(values: list[int]) -> int:
    clean = sorted(int(value) for value in values if value)
    if not clean:
        return 0
    return clean[min(len(clean) - 1, int(len(clean) * 0.95))]


def compare(old_path: pathlib.Path, new_path: pathlib.Path) -> int:
    old = {row["id"]: row for row in json.loads(
        old_path.read_text(encoding="utf-8"))["rows"]}
    new = {row["id"]: row for row in json.loads(
        new_path.read_text(encoding="utf-8"))["rows"]}
    regressions = []
    improvements = []
    for task_id, row in new.items():
        before = old.get(task_id)
        if before is None or row.get("manual"):
            continue
        if before["ok"] and not row["ok"]:
            regressions.append((task_id, row.get("issues")))
        elif not before["ok"] and row["ok"]:
            improvements.append(task_id)
    print(f"退化 {len(regressions)} 条，改进 {len(improvements)} 条")
    for task_id, issues in regressions:
        print(f"  ✗ {task_id}：{'；'.join(issues or [])}")
    for task_id in improvements:
        print(f"  ✓ {task_id}")
    return 1 if regressions else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden set 重放与对比")
    parser.add_argument("--tasks", type=pathlib.Path, default=DEFAULT_TASKS)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--compare", nargs=2, type=pathlib.Path, default=None)
    args = parser.parse_args()
    if args.compare:
        return compare(*args.compare)
    out = args.out or (ROOT / "docs" / "golden"
                       / f"结果-{time.strftime('%Y%m%d-%H%M%S')}.json")
    return run(load_tasks(args.tasks), out, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
