"""生活订阅送达报告（只读）：每条订阅最近 N 天出了几张卡、连续几天。

用法：
    python tools/life_delivery_report.py
    python tools/life_delivery_report.py --days 14 --json
    python tools/life_delivery_report.py --db D:\\学习系统\\learning.db

只读数据库，不生成卡片、不改订阅；「连续送达」按卡片日期算，
今天还没到点时不把今天算成断档（从昨天往前数）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _connect(path: pathlib.Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _card_days(conn, topic: str, start: str) -> set[str]:
    rows = conn.execute(
        "SELECT day FROM daily_cards WHERE domain = 'life' AND day >= ? "
        "AND (title = ? OR title LIKE ?)",
        (start, topic, f"{topic}·%")).fetchall()
    return {str(row["day"]) for row in rows}


def _streak(have: set[str], today: dt.date) -> int:
    cursor = today
    if cursor.isoformat() not in have:
        cursor -= dt.timedelta(days=1)   # 今天还没到点：从昨天往前数
    count = 0
    while cursor.isoformat() in have:
        count += 1
        cursor -= dt.timedelta(days=1)
    return count


def collect(db_path: pathlib.Path, days: int = 7,
            today: dt.date | None = None) -> dict:
    days = max(1, min(int(days or 7), 90))
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=days - 1)).isoformat()
    conn = _connect(db_path)
    try:
        subs = conn.execute(
            "SELECT id, topic, kind, cadence, at_time, last_run, enabled "
            "FROM subscriptions ORDER BY id").fetchall()
        items = []
        for sub in subs:
            have = _card_days(conn, str(sub["topic"]), start)
            items.append({
                "id": int(sub["id"]), "topic": str(sub["topic"]),
                "kind": str(sub["kind"]), "cadence": str(sub["cadence"]),
                "at_time": str(sub["at_time"]), "enabled": bool(sub["enabled"]),
                "last_run": str(sub["last_run"] or ""),
                "days_delivered": len(have),
                "streak": _streak(have, today) if sub["enabled"] else 0,
            })
    finally:
        conn.close()
    return {"db": str(db_path), "days": days, "start": start,
            "today": today.isoformat(), "subscriptions": items}


def render(data: dict) -> str:
    lines = [f"生活订阅送达报告 · 近 {data['days']} 天（{data['start']} 起）",
             f"库：{data['db']}"]
    if not data["subscriptions"]:
        lines.append("没有订阅。")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"{'主题':<16}{'类型':<8}{'送达':>6}{'连续':>6}  上次运行")
    for item in data["subscriptions"]:
        state = "" if item["enabled"] else "（已停用）"
        lines.append(
            f"{item['topic'][:14]:<16}{item['kind']:<8}"
            f"{item['days_delivered']:>4}/{data['days']:<2}"
            f"{item['streak']:>5}天  {item['last_run'] or '从未'}{state}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生活订阅送达报告（只读）")
    parser.add_argument("--db", default="", help="数据库路径；默认当前数据根")
    parser.add_argument("--days", type=int, default=7, help="看最近几天，默认 7")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    db_path = pathlib.Path(args.db) if args.db else None
    if db_path is None:
        from learnsys import config
        db_path = config.db_path()
    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1
    data = collect(db_path, days=args.days)
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
          else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
