"""六级实验闸门报告：从 `learning.db` 直接算成功线。

判据与口径见 `docs/施工单/闸门-六级实验.md`。

用法：
    .venv\\Scripts\\python.exe -X utf8 tools\\gate_report.py
    ... --start 2026-10-21 --days 14
    ... --db D:\\学习系统\\learning.db --json

只读打开数据库，不写任何表。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store                      # noqa: E402

ANALYSIS_KIND = "cet6_analyze"
STALE_PENDING_MINUTES = 10
SAMPLE_CSV = ROOT / "docs" / "闸门-抽检.csv"


def _pct(values: list[int], p: float) -> int | None:
    """最近秩法百分位；空列表返回 None。"""
    if not values:
        return None
    ordered = sorted(int(v) for v in values if v is not None and int(v) >= 0)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[index]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _parse_meta(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def collect(conn: sqlite3.Connection, start: dt.date, days: int) -> dict:
    """窗口内六条线所需的全部数字；缺表时返回空值而不是抛异常。"""
    begin = f"{start.isoformat()} 00:00:00"
    finish = f"{(start + dt.timedelta(days=days)).isoformat()} 00:00:00"
    now = dt.datetime.now()

    ask_rows = []
    if _table_exists(conn, "asks") and _table_exists(conn, "conversations"):
        ask_rows = conn.execute(
            "SELECT a.ts, a.first_ms, a.ms FROM asks a "
            "JOIN conversations c ON c.id = a.conversation_id "
            "WHERE c.module = 'cet6' AND a.ts >= ? AND a.ts < ?",
            (begin, finish)).fetchall()

    run_rows = []
    if _table_exists(conn, "service_runs"):
        run_rows = conn.execute(
            "SELECT ts, kind, meta_json, cache_hit FROM service_runs "
            "WHERE surface = 'cet6' AND ts >= ? AND ts < ?",
            (begin, finish)).fetchall()

    analysis_status: dict[str, int] = {}
    stale_pending = 0
    if _table_exists(conn, "service_results"):
        for status, count in conn.execute(
                "SELECT status, count(*) FROM service_results "
                "WHERE kind = ? AND created_at >= ? AND created_at < ? GROUP BY status",
                (ANALYSIS_KIND, begin, finish)).fetchall():
            analysis_status[str(status or "")] = int(count)
        cutoff = (now - dt.timedelta(minutes=STALE_PENDING_MINUTES)).strftime(
            "%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            "SELECT count(*) FROM service_results WHERE kind = ? AND status = 'pending' "
            "AND updated_at < ? AND created_at >= ? AND created_at < ?",
            (ANALYSIS_KIND, cutoff, begin, finish)).fetchone()
        stale_pending = int(row[0] if row else 0)

    progress_days: set[str] = set()
    if _table_exists(conn, "cet6_progress"):
        progress_days = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT substr(updated_at, 1, 10) FROM cet6_progress "
                "WHERE updated_at >= ? AND updated_at < ?",
                (begin, finish)).fetchall() if row[0]}

    event_days: set[str] = set()
    if _table_exists(conn, "cet6_events"):
        event_days = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT substr(ts, 1, 10) FROM cet6_events "
                "WHERE ts >= ? AND ts < ?", (begin, finish)).fetchall() if row[0]}

    per_day: dict[str, dict[str, int]] = {}

    def bucket(day: str) -> dict[str, int]:
        return per_day.setdefault(day, {"asks": 0, "translate": 0})

    for ts, first_ms, ms in ask_rows:
        bucket(str(ts)[:10])["asks"] += 1

    translate_actions = 0
    analysis_runs = 0
    cache_hits = 0
    for ts, kind, meta_raw, cache_hit in run_rows:
        if kind == "translate":
            bucket(str(ts)[:10])["translate"] += 1
            translate_actions += 1
            if cache_hit:
                cache_hits += 1
        elif kind == ANALYSIS_KIND:
            analysis_runs += 1
            if cache_hit:
                cache_hits += 1

    active_days = set(per_day) | progress_days | event_days
    # 有进度但没有问答/翻译的日子也算用过
    for day in active_days:
        bucket(day)

    first_values = [int(first_ms) for _, first_ms, _ in ask_rows if first_ms is not None]
    total_values = [int(ms) for _, _, ms in ask_rows if ms is not None]

    strict_days = sum(1 for day in per_day if per_day[day]["asks"] >= 3)
    loose_days = sum(1 for day in per_day
                     if per_day[day]["asks"] + per_day[day]["translate"] >= 3)

    sampled, correct = _read_sample()

    return {
        "start": start.isoformat(),
        "days": days,
        "end": (start + dt.timedelta(days=days - 1)).isoformat(),
        "elapsed_days": (now.date() - start).days + 1,
        "active_days": len(active_days),
        "active_dates": sorted(active_days),
        "strict_days": strict_days,
        "loose_days": loose_days,
        "per_day": {day: per_day[day] for day in sorted(per_day)},
        "asks": len(ask_rows),
        "translate_actions": translate_actions,
        "analysis_runs": analysis_runs,
        "analysis_status": analysis_status,
        "stale_pending": stale_pending,
        "cache_hits": cache_hits,
        "service_runs": analysis_runs + translate_actions,
        "first_ms_p95": _pct(first_values, 95),
        "total_ms_p95": _pct(total_values, 95),
        "sampled": sampled,
        "correct": correct,
    }


def _read_sample() -> tuple[int, int]:
    """读人工抽检 CSV：日期,抽样数,引用正确数,备注。"""
    if not SAMPLE_CSV.exists():
        return 0, 0
    sampled = correct = 0
    with SAMPLE_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                sampled += int(row.get("抽样数") or 0)
                correct += int(row.get("引用正确数") or 0)
            except (TypeError, ValueError):
                continue
    return sampled, correct


def _mark(ok: bool) -> str:
    return "达标" if ok else "未达标"


def _fmt_ms(value: int | None) -> str:
    return "无数据" if value is None else f"{value / 1000:.1f}s"


def format_report(data: dict) -> str:
    days = data["days"]
    elapsed = max(0, min(data["elapsed_days"], days))
    lines = [
        "学习工作台 · 六级实验闸门报告",
        f"窗口：{data['start']} → {data['end']}（共 {days} 天，已过 {elapsed} 天）",
        "",
        "一、使用天数",
        f"    {data['active_days']} / {days} 天，要求 ≥ 10 天　{_mark(data['active_days'] >= 10)}",
        "",
        "二、使用日每天 ≥ 3 次（带上下文提问 / 划词翻译）",
        f"    只算提问：{data['strict_days']} 天达标；提问+翻译：{data['loose_days']} 天达标",
        f"    要求 ≥ 8 个使用日　{_mark(data['strict_days'] >= 8)}",
        "",
        "三、分析结果丢失",
    ]
    status = data["analysis_status"]
    lost = int(status.get("error", 0)) + data["stale_pending"]
    if not status:
        lines.append("    还没有分析记录　无数据")
    else:
        lines.append(
            f"    错误 {int(status.get('error', 0))} 条，卡住超过 10 分钟 {data['stale_pending']} 条；"
            f"共 {sum(status.values())} 条　{_mark(lost == 0)}")
    lines += [
        "",
        "四、重复请求",
        (f"    {data['cache_hits']} / {data['service_runs']} 次命中缓存"
         f"（{_ratio(data['cache_hits'], data['service_runs'])}）　"
         f"{_mark(_ratio_value(data['cache_hits'], data['service_runs']) < 0.10)}")
        if data["service_runs"] else "    还没有服务调用　无数据",
        "",
        "五、延迟（仅六级提问）",
        f"    首 token P95：{_fmt_ms(data['first_ms_p95'])}（要求 < 2s）　"
        f"{_mark(data['first_ms_p95'] is not None and data['first_ms_p95'] < 2000)}",
        f"    完整回答 P95：{_fmt_ms(data['total_ms_p95'])}（要求 < 15s）　"
        f"{_mark(data['total_ms_p95'] is not None and data['total_ms_p95'] < 15000)}",
        "",
        "六、引用正确率（人工抽检，见 docs/闸门-抽检.csv）",
        f"    已抽 {data['sampled']} 次，正确 {data['correct']} 次　"
        f"{_mark(data['sampled'] >= 20 and data['correct'] >= 18)}",
        "",
        "每日明细：",
    ]
    if data["per_day"]:
        for day, item in data["per_day"].items():
            lines.append(f"    {day}  提问 {item['asks']}  翻译 {item['translate']}")
    else:
        lines.append("    窗口内还没有六级使用记录")

    if elapsed < days:
        lines.append("")
        lines.append(f"结论：窗口未结束，还剩 {days - elapsed} 天；到期后再看。")
    else:
        ok = (data["active_days"] >= 10 and data["strict_days"] >= 8 and lost == 0
              and _ratio_value(data["cache_hits"], data["service_runs"]) < 0.10
              and (data["first_ms_p95"] or 999999) < 2000
              and (data["total_ms_p95"] or 999999) < 15000
              and data["sampled"] >= 20 and data["correct"] >= 18)
        lines.append("")
        lines.append("结论：" + ("全部达标，可以进 P13。" if ok else "未全部达标，停止平台化，先打磨六级。"))
    return "\n".join(lines)


def _ratio_value(part: int, total: int) -> float:
    return (part / total) if total else 0.0


def _ratio(part: int, total: int) -> str:
    return "无请求" if not total else f"{part / total * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="六级实验闸门报告")
    parser.add_argument("--db", default="", help="学习库路径，缺省用 config.db_path()")
    parser.add_argument("--start", default="2026-10-21", help="窗口开始日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=14, help="窗口天数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    start = dt.date.fromisoformat(args.start)
    db_path = pathlib.Path(args.db) if args.db else config.db_path()
    if not db_path.exists():
        print(f"找不到学习库：{db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        data = collect(conn, start, args.days)
    finally:
        conn.close()

    data["db"] = str(db_path)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
