"""六级双写退休报告：从 `learning.db` 直接算「连续 14 天无差异」。

判据与口径见 `docs/施工单/P17.1-六级双写退休.md`。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\cet6_dualwrite_report.py
    ... --start 2026-10-21 --end 2026-11-04 --days 14
    ... --db D:\\学习系统\\learning.db --json
    ... --today 2026-11-04          # 测试用：固定“今天”

只读打开数据库，不写任何表。
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

CLEAN_STATUSES = {"ok", "ok_minor"}

# 2026-10-27 拍板的放宽口径：证据 5 天 / 干净 3 天 / 连续干净 1 天，
# 判定日 2026-11-09。严格口径（原施工单）仍是连续 14 天无差异。
RELAXED_MIN_EVIDENCE = 5
RELAXED_MIN_CLEAN = 3
RELAXED_MIN_STREAK = 1
RELAXED_JUDGE_DATE = dt.date(2026, 11, 9)
POLICIES = ("relaxed", "strict")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def _rows(conn: sqlite3.Connection, start: dt.date, end: dt.date) -> list[dict]:
    cur = conn.execute(
        "SELECT day, ts, paper_id, mode, compared, diff_fields, minor_fields, "
        "       missing_db, orphan_db, orphan_blocking, invalid, post_ok, status, hydration "
        "FROM cet6_dualwrite_runs WHERE day >= ? AND day <= ? ORDER BY day, id",
        (start.isoformat(), end.isoformat()))
    keys = ("day", "ts", "paper_id", "mode", "compared", "diff_fields", "minor_fields",
            "missing_db", "orphan_db", "orphan_blocking", "invalid", "post_ok",
            "status", "hydration")
    return [dict(zip(keys, row)) for row in cur.fetchall()]


def _run_clean(run: dict, strict_plays: bool) -> bool:
    if run["status"] not in CLEAN_STATUSES:
        return False
    if run["mode"] != "http":
        return False
    if not int(run["compared"] or 0):
        return False
    if int(run["diff_fields"] or 0) or int(run["missing_db"] or 0) \
            or int(run["orphan_blocking"] or 0) or int(run["invalid"] or 0):
        return False
    if not int(run["post_ok"] or 0):
        return False
    if strict_plays and int(run["minor_fields"] or 0):
        return False
    return True


def _day_clean(runs: list[dict], strict_plays: bool) -> bool:
    return bool(runs) and all(_run_clean(run, strict_plays) for run in runs)


def collect(*, db_path: pathlib.Path, start: dt.date, end: dt.date,
            required_days: int = 14, today: dt.date | None = None,
            strict_plays: bool = False, policy: str = "strict",
            min_evidence: int = RELAXED_MIN_EVIDENCE,
            min_clean: int = RELAXED_MIN_CLEAN,
            min_streak: int = RELAXED_MIN_STREAK,
            judge_date: dt.date | None = None) -> dict:
    """返回报告所需全部数字；缺库/缺表时抛 RuntimeError。

    `policy="strict"` 是原施工单的「连续 14 天无差异」；
    `policy="relaxed"` 是 2026-10-27 拍板的 5/3/1 口径，另加判定日。
    """
    if not db_path.exists():
        raise RuntimeError(f"数据库不存在：{db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(conn, "cet6_dualwrite_runs"):
            raise RuntimeError("数据库里还没有 cet6_dualwrite_runs 表（升级到 2.13.0 并打开一次试卷后才有）。")
        runs = _rows(conn, start, end)
        diffs = [dict(zip(("ts", "paper_id", "section", "item", "sentence", "field",
                           "kind", "local_value", "server_value"), row))
                 for row in conn.execute(
                     "SELECT ts, paper_id, section, item, sentence, field, kind, "
                     "       local_value, server_value FROM cet6_dualwrite_diffs "
                     "WHERE ts >= ? AND ts <= ? ORDER BY id DESC LIMIT 20",
                     (f"{start.isoformat()} 00:00:00", f"{end.isoformat()} 23:59:59"))]
    finally:
        conn.close()

    today = today or dt.date.today()
    horizon = min(end, today)
    by_day: dict[str, list[dict]] = {}
    for run in runs:
        by_day.setdefault(run["day"], []).append(run)

    observed = sorted(by_day)
    first_evidence = _date(observed[0]) if observed else None
    available_days = 0
    if first_evidence and horizon >= max(start, first_evidence):
        available_days = (horizon - max(start, first_evidence)).days + 1

    daily = []
    for day in sorted(by_day):
        group = by_day[day]
        daily.append({
            "day": day,
            "runs": len(group),
            "papers": len({r["paper_id"] for r in group}),
            "diff_fields": sum(int(r["diff_fields"] or 0) for r in group),
            "minor_fields": sum(int(r["minor_fields"] or 0) for r in group),
            "missing_db": sum(int(r["missing_db"] or 0) for r in group),
            "orphan_db": sum(int(r["orphan_db"] or 0) for r in group),
            "orphan_blocking": sum(int(r["orphan_blocking"] or 0) for r in group),
            "blocked": sum(1 for r in group if r["status"] == "blocked_empty"),
            "errored": sum(1 for r in group if r["status"] == "error"),
            "file_runs": sum(1 for r in group if r["mode"] != "http"),
            "clean": _day_clean(group, strict_plays),
        })

    # 连续段：从最早证据日到 horizon 逐日看；没有记录 = 未知，会打断。
    streak = 0
    streak_start: dt.date | None = None
    if first_evidence:
        cursor = max(start, first_evidence)
        cursor_end = max(cursor, horizon)
        while cursor <= cursor_end:
            group = by_day.get(cursor.isoformat())
            if group and _day_clean(group, strict_plays):
                if streak_start is None:
                    streak_start = cursor
                streak += 1
            else:
                streak = 0
                streak_start = None
            cursor += dt.timedelta(days=1)

    earliest = None
    if streak_start is not None:
        earliest = streak_start + dt.timedelta(days=max(0, required_days - 1))
        if streak >= required_days:
            earliest = streak_start + dt.timedelta(days=required_days - 1)

    clean_days = sum(1 for d in daily if d["clean"])
    judge_date = judge_date or RELAXED_JUDGE_DATE
    thresholds = [
        {"key": "evidence", "label": "证据天数", "need": min_evidence,
         "actual": len(observed)},
        {"key": "clean", "label": "干净天数", "need": min_clean,
         "actual": clean_days},
        {"key": "streak", "label": "连续干净", "need": min_streak,
         "actual": streak},
    ]
    for row in thresholds:
        row["ok"] = row["actual"] >= row["need"]
    thresholds_met = all(row["ok"] for row in thresholds)
    if policy == "relaxed":
        due = today >= judge_date
        eligible = bool(thresholds_met and due)
        if not due:
            earliest = judge_date
        elif thresholds_met:
            earliest = today
        else:
            earliest = None
        days_to_judge = max(0, (judge_date - today).days)
    else:
        due = True
        eligible = bool(streak >= required_days and available_days >= required_days)
        days_to_judge = 0
    return {
        "db": str(db_path),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "horizon": horizon.isoformat(),
        "required_days": required_days,
        "policy": policy,
        "thresholds": thresholds,
        "thresholds_met": thresholds_met,
        "judge_date": judge_date.isoformat(),
        "due": due,
        "days_to_judge": days_to_judge,
        "first_evidence": first_evidence.isoformat() if first_evidence else None,
        "available_days": available_days,
        "observed_days": len(observed),
        "clean_days": clean_days,
        "dirty_days": len(observed) - clean_days,
        "unknown_days": max(0, available_days - len(observed)) if first_evidence else 0,
        "streak": streak,
        "streak_start": streak_start.isoformat() if streak_start else None,
        "earliest_eligible": earliest.isoformat() if earliest else None,
        "eligible": eligible,
        "daily": daily,
        "diffs": diffs,
    }


def render(report: dict) -> str:
    if report.get("policy") == "relaxed":
        need = " / ".join(f"{row['label']}≥{row['need']}" for row in report["thresholds"])
        policy_line = f"政策：放宽口径（{need}；判定日 {report['judge_date']}）"
    else:
        policy_line = f"政策：严格口径（连续 {report['required_days']} 天无差异）"
    lines = ["六级双写退休报告（只读）",
             f"数据库：{report['db']}",
             policy_line,
             f"窗口：{report['start']} → {report['end']}"]
    if report["first_evidence"]:
        short = ""
        if (report.get("policy") != "relaxed"
                and report["available_days"] < report["required_days"]):
            short = "  ← 不足 {0} 天".format(report["required_days"])
        lines.append(f"证据起点：{report['first_evidence']}")
        lines.append(f"可用证据窗口：{report['first_evidence']} → {report['horizon']}"
                     f" = {report['available_days']} 天{short}")
    else:
        lines.append("证据起点：无（还没有任何整卷审计记录）")
    lines.append(f"已观测 {report['observed_days']} 天；干净 {report['clean_days']} 天；"
                 f"有差异 {report['dirty_days']} 天；未知 {report['unknown_days']} 天")
    if report["streak"]:
        lines.append(f"当前连续干净：{report['streak']} 天（起 {report['streak_start']}）")
    else:
        lines.append("当前连续干净：0 天")
    if report.get("policy") == "relaxed":
        for row in report["thresholds"]:
            lines.append(f"{row['label']}：{row['actual']} / 需要 {row['need']} "
                         + ("满足" if row["ok"] else "不足"))
        if report["due"]:
            lines.append(f"判定日：{report['judge_date']}（已到）")
        else:
            lines.append(f"判定日：{report['judge_date']}（今天 {report['today']}，"
                         f"还差 {report['days_to_judge']} 天）")
    lines.append(f"最早可能判定日：{report['earliest_eligible'] or '无法判断'}")
    if report.get("policy") == "relaxed":
        missing = [row["label"] for row in report["thresholds"] if not row["ok"]]
        if report["eligible"]:
            lines.append("结论：满足放宽判据，可以按计划退休。")
        elif not report["due"] and report["thresholds_met"]:
            lines.append(f"结论：门槛已满足，但未到判定日（还差 {report['days_to_judge']} 天）。")
        elif not report["due"]:
            lines.append(f"结论：未到判定日，且门槛未满足（缺：{'、'.join(missing)}）。")
        else:
            lines.append(f"结论：判定日已到，但门槛未满足（缺：{'、'.join(missing)}），不能退休。")
    elif report["eligible"]:
        lines.append("结论：满足判据，可以按计划退休。")
    elif report["available_days"] < report["required_days"]:
        lines.append("结论：证据天数不足，不能按原计划切换。")
    else:
        lines.append("结论：未满足「连续无差异」，先查差异再决定。")

    if report["daily"]:
        lines.append("")
        lines.append("每日明细：")
        lines.append("日期        次数 卷数 差异 次要 缺失 孤儿 阻断 文件 状态")
        for d in report["daily"]:
            lines.append(f"{d['day']}  {d['runs']:>4} {d['papers']:>4} "
                         f"{d['diff_fields']:>4} {d['minor_fields']:>4} "
                         f"{d['missing_db']:>4} {d['orphan_db']:>4} "
                         f"{d['blocked']:>4} {d['file_runs']:>4} "
                         + ("干净" if d["clean"] else "不干净"))
    if report["diffs"]:
        lines.append("")
        lines.append("最近差异：")
        for item in report["diffs"]:
            lines.append(f"{item['ts']} {item['paper_id']} / {item['section']} / "
                         f"{item['item']} / 第{item['sentence']}句 / {item['field']}"
                         f"（{item['kind']}）：本地={item['local_value']} 服务端={item['server_value']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="六级双写退休报告（只读）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--start", default="2026-10-21")
    parser.add_argument("--end", default="",
                        help="结束日期（YYYY-MM-DD）；留空 = 今天（或 --today）")
    parser.add_argument("--days", type=int, default=14, dest="required_days",
                        help="严格口径要求的连续干净天数（默认 14）")
    parser.add_argument("--policy", choices=POLICIES, default="relaxed",
                        help="relaxed = 2026-10-27 拍板的 5/3/1 放宽口径（默认）；"
                             "strict = 原施工单连续 N 天")
    parser.add_argument("--judge-date", default=RELAXED_JUDGE_DATE.isoformat(),
                        help="放宽口径的判定日（默认 2026-11-09）")
    parser.add_argument("--today", default="", help="测试用：固定今天（YYYY-MM-DD）")
    parser.add_argument("--strict-plays", action="store_true", help="仅 plays 的差异也阻断")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    today = _date(args.today) if args.today else dt.date.today()
    end = _date(args.end) if args.end else today
    try:
        report = collect(
            db_path=pathlib.Path(args.db), start=_date(args.start), end=end,
            required_days=args.required_days, today=today,
            strict_plays=args.strict_plays, policy=args.policy,
            judge_date=_date(args.judge_date))
    except RuntimeError as exc:
        print(f"无法生成报告：{exc}")
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0 if report["eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
