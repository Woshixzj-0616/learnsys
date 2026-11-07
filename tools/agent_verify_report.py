"""P32 验收报告：最近任务里有多少「跑完了但没验过 / 验不过」。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\agent_verify_report.py
    ... --limit 50 --json
    ... --db D:\\学习系统\\learning.db

只读打开数据库，不写任何表。口径见 `learnsys/services/agents/warden.py`：
`done` 只是进程正常退出；`verdict_state=passed` 才说明按契约验过了。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config                                  # noqa: E402

LABELS = {"passed": "通过", "failed": "未通过", "skipped": "未验证",
          "error": "验收出错", "": "未验证（老任务）"}


def _load(conn: sqlite3.Connection, limit: int) -> list[dict]:
    # 旧库还没升 schema 时也要能跑：缺列就按空值处理。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_tasks)")}
    state = "verdict_state" if "verdict_state" in cols else "''"
    verdict = "verdict_json" if "verdict_json" in cols else "''"
    rows = conn.execute(
        f"SELECT id, agent, mode, status, created_at, {state}, {verdict} "
        "FROM agent_tasks ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    items = []
    for row in rows:
        try:
            verdict = json.loads(row[6] or "{}")
        except (json.JSONDecodeError, TypeError):
            verdict = {}
        items.append({
            "id": int(row[0]), "agent": row[1] or "", "mode": row[2] or "read",
            "status": row[3] or "", "created_at": row[4] or "",
            "state": row[5] or "", "verdict": verdict if isinstance(verdict, dict) else {},
        })
    return items


def _counts(items: list[dict]) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0, "": 0}
    for item in items:
        counts[item["state"] if item["state"] in counts else "error"] += 1
    return counts


def _print(items: list[dict], counts: dict[str, int]) -> None:
    total = len(items)
    print(f"验收报告（最近 {total} 条任务）")
    print("")
    print("| 结论 | 条数 |")
    print("|---|---|")
    for key in ("passed", "failed", "error", "skipped", ""):
        print(f"| {LABELS[key]} | {counts.get(key, 0)} |")
    verified = counts["passed"] + counts["failed"] + counts["error"]
    print("")
    if total:
        print(f"有验收记录：{verified}/{total}；"
              f"通过率 {counts['passed'] / max(1, verified):.0%}（不含未验证）")
    else:
        print("还没有任务。")
    problems = [item for item in items
                if item["state"] in ("failed", "error")]
    if problems:
        print("")
        print("未通过 / 出错的检查：")
        for item in problems:
            verdict = item["verdict"]
            summary = verdict.get("summary") or LABELS.get(item["state"], "")
            print(f"  #{item['id']} {item['agent']} {item['mode']} · "
                  f"{LABELS.get(item['state'], item['state'])} · "
                  f"{summary} · {item['created_at']}")
            for check in verdict.get("items") or []:
                if check.get("ok"):
                    continue
                detail = check.get("detail") or check.get("actual") or ""
                print(f"    - {check.get('check')}：{detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="学习工作台 Agent 验收报告")
    parser.add_argument("--limit", type=int, default=20, help="看最近多少条（1–200）")
    parser.add_argument("--db", default="", help="数据库路径，默认生产库")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    limit = max(1, min(int(args.limit or 20), 200))
    db = pathlib.Path(args.db) if args.db else pathlib.Path(config.db_path())
    if not db.is_file():
        print(f"数据库不存在：{db}")
        return 1
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        items = _load(conn, limit)
    finally:
        conn.close()
    counts = _counts(items)
    if args.json:
        print(json.dumps({"db": str(db), "counts": counts, "items": items},
                         ensure_ascii=False, indent=2))
    else:
        _print(items, counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
