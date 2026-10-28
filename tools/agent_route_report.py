"""外部 agent 影子路由报告：建议与实际选择的一致率。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\agent_route_report.py
    ... --days 30 --limit 50 --json
    ... --db D:\\学习系统\\learning.db

只读打开数据库，不写任何表。口径见 `learnsys/services/agents/route.py`：
`done` 只是任务正常结束，**不是正确性**；一致率只说明建议与人工选择的重合度。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config                                  # noqa: E402
from learnsys.services.agents.route import stats             # noqa: E402


def _load(conn: sqlite3.Connection, since: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, agent, mode, status, duration_ms, cost_usd, route_json, created_at "
        "FROM agent_tasks WHERE created_at >= ? ORDER BY id DESC",
        (since,)).fetchall()
    items = []
    for row in rows:
        try:
            route = json.loads(row[6] or "{}")
        except (json.JSONDecodeError, TypeError):
            route = {}
        items.append({
            "id": int(row[0]), "agent": row[1] or "", "mode": row[2] or "read",
            "status": row[3] or "", "duration_ms": int(row[4] or 0),
            "cost_usd": float(row[5] or 0),
            "route": route if isinstance(route, dict) else {},
            "created_at": row[7] or "",
        })
    return items


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.0f} 秒" if ms else "—"


def _summary(items: list[dict]) -> dict:
    with_route = [item for item in items if item["route"].get("recommended")]
    agree = [item for item in with_route
             if item["route"].get("recommended") == item["route"].get("chosen")]
    disagreements = [item for item in with_route
                     if item["route"].get("recommended") != item["route"].get("chosen")]
    distribution: dict[str, int] = {}
    for item in with_route:
        key = str(item["route"].get("recommended"))
        distribution[key] = distribution.get(key, 0) + 1
    agents: dict[str, dict] = {}
    for item in items:
        agents.setdefault(item["agent"], []).append(item)
    return {
        "tasks": len(items),
        "with_route": len(with_route),
        "agree": len(agree),
        "agree_rate": round(len(agree) / len(with_route), 3) if with_route else 0.0,
        "recommended": distribution,
        "agents": {agent: stats(rows) for agent, rows in sorted(agents.items())},
        "disagreements": [
            {"id": item["id"], "created_at": item["created_at"],
             "chosen": item["route"].get("chosen"), "recommended": item["route"].get("recommended"),
             "reason": item["route"].get("reason") or ""}
            for item in disagreements
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="外部 agent 影子路由报告")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = pathlib.Path(args.db)
    if not path.exists():
        print(f"找不到数据库：{path}")
        return 1
    days = max(0, int(args.days or 0))
    since = "" if not days else (
        dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        items = _load(conn, since)
    finally:
        conn.close()
    data = _summary(items)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    window = f"最近 {days} 天" if days else "全部"
    print("影子路由报告（只读）")
    print(f"数据库：{path}")
    print(f"窗口：{window}；任务 {data['tasks']}；带路由建议 {data['with_route']}")
    if not data["with_route"]:
        print("还没有影子记录：先在 Agent 中枢派几个任务。")
        return 0
    print(f"建议与选择一致：{data['agree']}/{data['with_route']}"
          f"（{data['agree_rate'] * 100:.1f}%）")
    print("建议分布：" + " · ".join(
        f"{key} {value}" for key, value in
        sorted(data["recommended"].items(), key=lambda item: -item[1])))
    print("\n各 agent 历史（done 只代表任务正常结束，不代表结果正确）：")
    for agent, stat in data["agents"].items():
        cost = (f"${stat['median_cost']:.4f}" if stat["median_cost"] is not None
                else "无自报费用")
        print(f"  {agent}: 完成 {stat['done']}/{stat['n']}，"
              f"中位耗时 {_seconds(stat['median_ms'])}，单次费用 {cost}")
    if data["disagreements"]:
        print("\n分歧样本（建议与实际选择不同）：")
        for item in data["disagreements"][:max(1, int(args.limit or 10))]:
            print(f"  #{item['id']} {item['created_at']} 选 {item['chosen']} / "
                  f"建议 {item['recommended']} · {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
