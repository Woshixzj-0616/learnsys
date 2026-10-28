"""学习记录时长：实测 + 有上限的估算，分开记账。

口径只在这里定义一处，`/api/overview` 与 `/api/today` 共用：

- **实测**：`sessions`（专注，真实起止）、`transcripts`（课堂转写，真实起止）、
  `train_submissions.duration_s`（写作/翻译提交，真实秒数）。
- **估算**：没有起止的动作按可解释的上限折算，全部标「估算」——
  六级精听 = 每段录音每天「不同句子数 × 2 分钟」，单段封顶 30；
  问答 = 每条 2 分钟，每天封顶 20；复习 = 每张 0.5 分钟，封顶 20；
  网工训练 = 每格 15 分钟，封顶 30；测验 = 每场 5 分钟，封顶 15；
  资料问答/出题 = 每次 2 分钟，封顶 10。

**断点按次数只进 `activity`，不再一条 2 分钟折算。** 今日目标看任务完成，
时间只做预算和参考，不参与达标判定。
"""
from __future__ import annotations

import datetime
import sqlite3

# 估算上限：数字写在这里，页面只读结果，不在前端再算一份。
CET6_MINUTES_PER_SENTENCE = 2.0
CET6_MAX_PER_RECORDING = 30.0
ASK_MINUTES = 2.0
ASK_MAX_PER_DAY = 20.0
REVIEW_MINUTES_PER_CARD = 0.5
REVIEW_MAX_PER_DAY = 20.0
NETLAB_MINUTES_PER_CARD = 15.0
NETLAB_MAX_PER_DAY = 30.0
QUIZ_MINUTES_PER_SESSION = 5.0
QUIZ_MAX_PER_DAY = 15.0
MATERIAL_MINUTES_PER_ACTION = 2.0
MATERIAL_MAX_PER_DAY = 10.0


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


def merge_spans(spans: list[tuple]) -> list[tuple]:
    """区间并集：重叠 / 相邻的段合成一段。"""
    if not spans:
        return []
    ordered = sorted(spans)
    out = [list(ordered[0])[:2]]
    for start, end in ordered[1:]:
        if start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(start, end) for start, end in out]


def merge_minutes(spans: list[tuple]) -> float:
    """区间并集的总分钟数（重叠部分只算一次）。"""
    return sum((end - start).total_seconds() for start, end in merge_spans(spans)) / 60.0


def _safe_rows(conn, sql: str, args=()) -> list:
    """旧库 / 精简测试库可能缺表：缺表当 0，不让一个统计拖垮整个今日页。"""
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _safe_count(conn, sql: str, args=()) -> int:
    rows = _safe_rows(conn, sql, args)
    return int(rows[0][0] or 0) if rows else 0


def _day_like(day: str) -> str:
    return f"{str(day)[:10]}%" if day else "%"


def _measured_spans(conn, day: str, now: datetime.datetime) -> tuple[list[tuple], list[tuple]]:
    """返回 (专注区间, 转写区间)，跨午夜按当天裁。"""
    if day:
        lo, hi = day_bounds(day)
        lo_text = lo.strftime("%Y-%m-%d %H:%M:%S")
        hi_text = hi.strftime("%Y-%m-%d %H:%M:%S")
        focus_rows = _safe_rows(
            conn,
            "SELECT started_at, COALESCE(ended_at, '') FROM sessions "
            "WHERE started_at < ? AND (ended_at = '' OR ended_at > ?)",
            (hi_text, lo_text))
        transcript_rows = _safe_rows(
            conn,
            "SELECT ts_start, ts_end FROM transcripts "
            "WHERE ts_start < ? AND ts_end > ?", (hi_text, lo_text))
    else:
        focus_rows = _safe_rows(
            conn, "SELECT started_at, COALESCE(ended_at, '') FROM sessions")
        transcript_rows = _safe_rows(
            conn, "SELECT ts_start, ts_end FROM transcripts")

    focus = []
    for started, ended in focus_rows:
        start = parse_ts(started)
        if start is None:
            continue
        end = parse_ts(ended) or now
        if end > start:
            focus.append((start, end))

    transcripts = []
    for started, ended in transcript_rows:
        start, end = parse_ts(started), parse_ts(ended)
        if start is not None and end is not None and end > start:
            transcripts.append((start, end))
    return focus, transcripts


def _cet6_estimate(conn, day: str) -> tuple[float, int, int]:
    """六级精听估算：每段录音按「不同句子数 × 2 分钟」，单段封顶 30。

    同一条句子按 188 次断点也只算一次；返回 (分钟, 断点次数, 不同句子数)。
    """
    rows = _safe_rows(
        conn,
        "SELECT substr(ts, 1, 10), "
        "COALESCE(NULLIF(paper_id, ''), COALESCE(paper_title, '')), "
        "COALESCE(section, ''), COALESCE(item, ''), COALESCE(sentence, 0) "
        "FROM cet6_events WHERE ts LIKE ?", (_day_like(day),))
    groups: dict[tuple, set] = {}
    for stamp, paper, section, item, sentence in rows:
        key = (stamp, paper, section, item)
        groups.setdefault(key, set()).add(int(sentence or 0) or str(item))
    minutes = sum(min(len(sentences) * CET6_MINUTES_PER_SENTENCE,
                      CET6_MAX_PER_RECORDING) for sentences in groups.values())
    sentences = sum(len(sentences) for sentences in groups.values())
    return minutes, len(rows), sentences


def recorded(conn, day: str = "") -> dict:
    """当天的学习记录。

    返回：
    - `minutes` 总记录分钟（实测 + 估算，仅展示，不参与目标判定）
    - `measured` / `estimated` 实测与估算各多少
    - `breakdown` 按来源拆开（相加等于 `minutes`）
    - `activity` 断点/问答/复习/训练/测验/资料的动作次数
    """
    now = datetime.datetime.now()
    like = _day_like(day)

    focus, transcripts = _measured_spans(conn, day, now)
    focus = clip(focus, day)
    transcripts = clip(transcripts, day)

    breakdown: dict[str, float] = {}
    measured_spans: list[tuple] = []
    measured = 0.0
    for name, spans in (("focus", focus), ("transcript", transcripts)):
        before = measured
        measured_spans.extend(spans)
        measured = merge_minutes(measured_spans)
        gain = round(measured - before, 1)
        if gain:
            breakdown[name] = gain

    # 训练提交有真实秒数；落在专注/转写区间内的，视为已经被实测覆盖。
    train_rows = _safe_rows(
        conn,
        "SELECT created_at, updated_at, duration_s FROM train_submissions "
        "WHERE duration_s > 0"
        + (" AND substr(updated_at, 1, 10) = ?" if day else ""),
        (str(day)[:10],) if day else ())
    covered = merge_spans(measured_spans)
    train_minutes = 0.0
    for created, updated, seconds in train_rows:
        stamp = parse_ts(created) or parse_ts(updated)
        if stamp is not None and any(start <= stamp <= end for start, end in covered):
            continue
        train_minutes += max(0.0, float(seconds or 0)) / 60.0
    if train_minutes:
        measured += train_minutes
        breakdown["train"] = round(train_minutes, 1)

    cet6_minutes, breakpoints, sentences = _cet6_estimate(conn, day)
    asks = _safe_count(conn, "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (like,))
    reviews = _safe_count(
        conn, "SELECT COUNT(*) FROM review_log"
        + (" WHERE substr(ts, 1, 10) = ?" if day else ""),
        (str(day)[:10],) if day else ())
    netlab = _safe_count(
        conn, "SELECT COUNT(*) FROM events WHERE module = 'netlab' AND ts LIKE ?",
        (like,))
    quizzes = _safe_count(
        conn, "SELECT COUNT(*) FROM events WHERE module = 'quiz' "
        "AND kind = 'quiz' AND ts LIKE ?", (like,))
    materials = _safe_count(
        conn, "SELECT COUNT(*) FROM events WHERE module = 'materials' "
        "AND kind IN ('ask', 'quiz') AND ts LIKE ?", (like,))
    trains = _safe_count(
        conn, "SELECT COUNT(*) FROM train_submissions "
        "WHERE status IN ('reviewed', 'failed')"
        + (" AND substr(updated_at, 1, 10) = ?" if day else ""),
        (str(day)[:10],) if day else ())

    estimated_parts = {
        "cet6": cet6_minutes,
        "asks": min(asks * ASK_MINUTES, ASK_MAX_PER_DAY),
        "review": min(reviews * REVIEW_MINUTES_PER_CARD, REVIEW_MAX_PER_DAY),
        "netlab": min(netlab * NETLAB_MINUTES_PER_CARD, NETLAB_MAX_PER_DAY),
        "quiz": min(quizzes * QUIZ_MINUTES_PER_SESSION, QUIZ_MAX_PER_DAY),
        "materials": min(materials * MATERIAL_MINUTES_PER_ACTION,
                         MATERIAL_MAX_PER_DAY),
    }
    estimated = 0.0
    for name, value in estimated_parts.items():
        value = round(float(value), 1)
        if value > 0:
            breakdown[name] = value
            estimated += value

    return {
        "minutes": round(measured + estimated, 1),
        "measured": round(measured, 1),
        "estimated": round(estimated, 1),
        "breakdown": breakdown,
        "activity": {
            "breakpoints": breakpoints,
            "sentences": sentences,
            "asks": asks,
            "reviews": reviews,
            "trains": trains,
            "quizzes": quizzes,
            "materials": materials,
        },
    }


def study(conn, day: str = "") -> tuple[float, dict[str, float]]:
    """兼容旧调用：返回 (总分钟, 构成)。新代码请用 `recorded()` 拿实测/估算。"""
    data = recorded(conn, day)
    return data["minutes"], data["breakdown"]
