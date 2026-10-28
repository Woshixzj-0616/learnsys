"""有效学习分钟：专注 ∪ 转写 ∪ 事件，按分钟并集去重。

口径只在这里定义一处，`/api/overview` 和 `/api/today` 共用：
- 视频/窗口记录的 sessions 区间有真实起止；
- transcripts 有真实起止（通常落在 session 内，合并后不重复）；
- 问答 / 六级断点 / 训练 / 复盘没有时长，按 2 分钟一段，相邻事件只算一次。

目标是「今天投入了多久」，不是「产生了多少事件」，所以重叠一律只算一次。
"""
from __future__ import annotations

import datetime

# 没有真实时长的行为按 2 分钟算一段；相邻事件落在同一段里只算一次。
EVENT_MINUTES = 2.0

# 哪些 events.module 算学习投入（浏览器/资料打开不算，避免把刷网页算成学习）。
STUDY_MODULES = ("netlab", "review", "quiz", "train", "materials")


def parse_ts(value) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def day_bounds(day: str) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime.strptime(day, "%Y-%m-%d")
    return start, start + datetime.timedelta(days=1)


def clip(spans: list[tuple], day: str) -> list[tuple]:
    """把跨午夜的区间裁到指定那一天，避免昨天 23:50 的录像算进今天。"""
    if not day:
        return spans
    lo, hi = day_bounds(day)
    out = []
    for start, end in spans:
        left, right = max(start, lo), min(end, hi)
        if right > left:
            out.append((left, right))
    return out


def merge_minutes(spans: list[tuple]) -> float:
    """区间并集的总分钟数（重叠部分只算一次）。"""
    if not spans:
        return 0.0
    ordered = sorted(spans)
    total = 0.0
    cur_start, cur_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
    total += (cur_end - cur_start).total_seconds()
    return total / 60.0


def study(conn, day: str = "") -> tuple[float, dict[str, float]]:
    """有效学习分钟。返回 (总分钟, 构成)。

    构成按加入顺序归属 —— 先专注、再转写、再事件，所以每类只记
    「它新贡献了多少分钟」，各项相加等于总数（不会出现 30+10+6=46 但总 30 的怪账）。
    """
    like = f"{day}%" if day else "%"
    now = datetime.datetime.now()
    groups: list[tuple[str, list[tuple]]] = []

    # 跨午夜的录像/转写要按「区间与当天相交」筛，不能只看 started_at 属于哪天。
    if day:
        lo, hi = day_bounds(day)
        lo_text = lo.strftime("%Y-%m-%d %H:%M:%S")
        hi_text = hi.strftime("%Y-%m-%d %H:%M:%S")
        session_rows = conn.execute(
            "SELECT started_at, COALESCE(ended_at, '') FROM sessions "
            "WHERE started_at < ? AND (ended_at = '' OR ended_at > ?)",
            (hi_text, lo_text))
        transcript_rows = conn.execute(
            "SELECT ts_start, ts_end FROM transcripts "
            "WHERE ts_start < ? AND ts_end > ?", (hi_text, lo_text))
    else:
        session_rows = conn.execute(
            "SELECT started_at, COALESCE(ended_at, '') FROM sessions")
        transcript_rows = conn.execute(
            "SELECT ts_start, ts_end FROM transcripts")

    focus = []
    for started, ended in session_rows:
        start = parse_ts(started)
        if start is None:
            continue
        end = parse_ts(ended) or now
        if end > start:
            focus.append((start, end))
    groups.append(("focus", focus))

    transcripts = []
    for started, ended in transcript_rows:
        start, end = parse_ts(started), parse_ts(ended)
        if start is not None and end is not None and end > start:
            transcripts.append((start, end))
    groups.append(("transcript", transcripts))

    events = []
    for (stamp,) in conn.execute("SELECT ts FROM asks WHERE ts LIKE ?", (like,)):
        start = parse_ts(stamp)
        if start is not None:
            events.append((start, start + datetime.timedelta(minutes=EVENT_MINUTES)))
    for (stamp,) in conn.execute("SELECT ts FROM cet6_events WHERE ts LIKE ?", (like,)):
        start = parse_ts(stamp)
        if start is not None:
            events.append((start, start + datetime.timedelta(minutes=EVENT_MINUTES)))
    marks = ",".join("?" * len(STUDY_MODULES))
    for (stamp,) in conn.execute(
            f"SELECT ts FROM events WHERE ts LIKE ? AND module IN ({marks})",
            (like, *STUDY_MODULES)):
        start = parse_ts(stamp)
        if start is not None:
            events.append((start, start + datetime.timedelta(minutes=EVENT_MINUTES)))
    groups.append(("activity", events))

    merged: list[tuple] = []
    breakdown: dict[str, float] = {}
    for name, spans in groups:
        spans = clip(spans, day)
        if not spans:
            continue
        before = merge_minutes(merged)
        merged.extend(spans)
        after = merge_minutes(merged)
        gain = round(after - before, 1)
        if gain:
            breakdown[name] = gain
    return round(merge_minutes(merged), 1), breakdown
