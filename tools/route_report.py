"""影子路由报告：从 agent_runs 的 trace 里汇总「如果自动路由会怎么选」。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\route_report.py
    ... --days 30 --json
    ... --db D:\\学习系统\\learning.db

只读打开数据库，不写任何表。判据与规则见 `learnsys/agent/router.py`。
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
from learnsys.store.agent_runs import route_stats            # noqa: E402


def _fmt_counts(counts: dict) -> str:
    if not counts:
        return "—"
    return " · ".join(f"{key} {value}" for key, value in
                      sorted(counts.items(), key=lambda item: -item[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="影子路由报告")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = pathlib.Path(args.db)
    if not path.exists():
        print(f"找不到数据库：{path}")
        return 1
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        stats = route_stats(conn, days=args.days)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    window = f"最近 {args.days} 天" if args.days else "全部"
    print("影子路由报告（只读）")
    print(f"数据库：{path}")
    print(f"窗口：{window}" + (f"（since {stats['since']}）" if stats["since"] else ""))
    print(f"运行总数：{stats['runs']}；带路由记录：{stats['with_route']}；"
          f"建议升级：{stats['escalations']}（{stats['escalation_rate'] * 100:.1f}%）")
    if not stats["with_route"]:
        print("还没有影子记录：确认设置里 auto_route=shadow，并先用工作台问几轮。")
        return 0
    print(f"实际档位：{_fmt_counts(stats['actual_tiers'])}")
    print(f"建议档位：{_fmt_counts(stats['recommended_tiers'])}")
    print(f"建议模型：{_fmt_counts(stats['recommended_models'])}")
    print(f"路由模式：{_fmt_counts(stats['auto_modes'])}")
    if stats["reasons"]:
        print("\n建议理由 Top：")
        for item in stats["reasons"]:
            print(f"  {item['reason']}：{item['count']}")
    print("\n每日明细：")
    print("日期        运行  有路由  建议升级")
    for day in stats["daily"]:
        print(f"{day['day']}  {day['runs']:>4}  {day['routes']:>6}  {day['escalations']:>8}")
    if stats["samples"]:
        print("\n升级样本：")
        for sample in stats["samples"]:
            print(f"  [{sample['model']}] {sample['question']}  ← {sample['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
