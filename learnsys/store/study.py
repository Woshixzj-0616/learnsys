"""学习记录域：会话、前台窗口事件、声音转写、快照文字、专注统计。"""
from __future__ import annotations

import datetime as dt
import sqlite3

from learnsys.core import db as core_db
from ._base import _LOCK, now


def start_session(conn: sqlite3.Connection) -> int:
    with _LOCK:
        cur = conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (now(),))
        conn.commit()
        return int(cur.lastrowid or 0)


def end_session(conn: sqlite3.Connection, session_id: int) -> None:
    with _LOCK:
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (now(), session_id))
        conn.commit()


def add_window_event(conn: sqlite3.Connection, session_id: int, process: str, title: str) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO window_events (session_id, ts, process, title) VALUES (?, ?, ?, ?)",
            (session_id, now(), process, title),
        )
        conn.commit()


def add_window_event_at(conn: sqlite3.Connection, session_id: int, ts: str,
                        process: str, title: str) -> None:
    """指定时刻的窗口事件（测试/补录用 —— 正常采集走 add_window_event）。"""
    with _LOCK:
        conn.execute(
            "INSERT INTO window_events (session_id, ts, process, title) VALUES (?, ?, ?, ?)",
            (session_id, ts, process, title),
        )
        conn.commit()


def add_transcript(conn: sqlite3.Connection, session_id: int, ts_start: str, ts_end: str, text: str) -> None:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO transcripts (session_id, ts_start, ts_end, text) VALUES (?, ?, ?, ?)",
            (session_id, ts_start, ts_end, text),
        )
        conn.commit()
        row_id = int(cur.lastrowid or 0)
    core_db.index_row(conn, "transcript", row_id, ts_start, text)


def session_exists(conn: sqlite3.Connection, session_id: int) -> bool:
    return conn.execute("SELECT 1 FROM sessions WHERE id = ?",
                        (int(session_id),)).fetchone() is not None


def session_title(conn: sqlite3.Connection, session_id: int) -> str:
    row = conn.execute("SELECT title FROM sessions WHERE id = ?",
                       (int(session_id),)).fetchone()
    return str(row[0] or "") if row else ""


def session_stats(conn: sqlite3.Connection, session_id: int) -> dict:
    with _LOCK:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT title) FROM window_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        trow = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return {
        "窗口行数": int(row[0] or 0),
        "不同窗口": int(row[1] or 0),
        "转写条数": int(trow[0] or 0),
        "转写字数": int(trow[1] or 0),
    }


def session_windows(conn: sqlite3.Connection, session_id: int):
    """这段记录里记下的窗口（按时间升序）—— 变了才记一条，所以**一行 = 一次切换**。"""
    with _LOCK:
        return conn.execute(
            "SELECT ts, process, title FROM window_events WHERE session_id = ? ORDER BY ts, id",
            (session_id,),
        ).fetchall()


def minutes(start: str, end: str) -> float:
    """两个 'YYYY-MM-DD HH:MM:SS' 之间差了多少分钟（算不出来就当 0）。"""
    try:
        return (dt.datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
                - dt.datetime.strptime(start, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0
    except Exception:
        return 0.0


def session_summary(conn: sqlite3.Connection, session_id: int, ended_at: str = "") -> dict:
    """这段记录的一句话总结：记了多久、切了几次窗口、最久停在哪个程序。

    停留时长 = 「下一条的时间 − 这条的时间」，最后一条算到结束时刻。
    总时长看的是 session 的开始/结束，不是把每段加起来（中间程序没跑也算在内）。
    """
    with _LOCK:
        head = conn.execute(
            "SELECT started_at, ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        rows = conn.execute(
            "SELECT ts, process FROM window_events WHERE session_id = ? ORDER BY ts, id",
            (session_id,)).fetchall()
    if not head:
        return {"分钟": 0.0, "切换": 0, "最久": ("", 0.0)}
    end = ended_at or head[1] or now()
    total = minutes(head[0], end)
    per: dict[str, float] = {}
    for i, (ts, process) in enumerate(rows):
        stop = rows[i + 1][0] if i + 1 < len(rows) else end
        name = (process or "未知")
        if name.lower().endswith(".exe"):
            name = name[:-4]
        per[name] = per.get(name, 0.0) + max(0.0, minutes(ts, stop))
    top = max(per.items(), key=lambda kv: kv[1]) if per else ("", 0.0)
    # 第一行是「开始时在看的那个窗口」，不是切换 ⇒ 切换次数 = 行数 − 1
    switches = max(0, len(rows) - 1)
    return {"分钟": round(total, 1), "切换": switches, "最久": (top[0], round(top[1], 1))}


def last_transcript(conn: sqlite3.Connection, session_id: int):
    with _LOCK:
        return conn.execute(
            "SELECT ts_start, ts_end, text FROM transcripts WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()


def search_transcripts(conn: sqlite3.Connection, keyword: str = "", session_id=None,
                       ts_from: str = "", ts_to: str = "", limit: int = 50):
    """给 AI / 自己查：按关键词 + 时间区间取转写片段（时间都是 'YYYY-MM-DD HH:MM:SS'）。"""
    where, args = [], []
    if keyword:
        where.append("text LIKE ?")
        args.append(f"%{keyword}%")
    if session_id is not None:
        where.append("session_id = ?")
        args.append(session_id)
    if ts_from:
        where.append("ts_start >= ?")
        args.append(ts_from)
    if ts_to:
        where.append("ts_end <= ?")
        args.append(ts_to)
    sql = "SELECT session_id, ts_start, ts_end, text FROM transcripts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts_start LIMIT ?"
    args.append(limit)
    with _LOCK:
        return conn.execute(sql, args).fetchall()


def window_titles(conn: sqlite3.Connection, ts_from: str = "", ts_to: str = "", limit: int = 50):
    """按时间区间取「那会儿在看什么窗口」（给 AI 认「这段在讲哪一节课」）。"""
    where, args = [], []
    if ts_from:
        where.append("ts >= ?")
        args.append(ts_from)
    if ts_to:
        where.append("ts <= ?")
        args.append(ts_to)
    sql = "SELECT ts, process, title FROM window_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts LIMIT ?"
    args.append(limit)
    with _LOCK:
        return conn.execute(sql, args).fetchall()
def focus_stats(conn: sqlite3.Connection, until: str = "", day: str = "") -> dict:
    """这一天的专注统计：记了多久、切了几次、各程序停留多久（前 5）。

    停留口径和 session_summary 一致：下一条事件的时间 − 这条的时间，末条算到结束时刻。
    未结束的 session 算到 until（缺省 = 现在）。
    `day` = 'YYYY-MM-DD'：统一库下只统计那天的 session / 事件。
    """
    with _LOCK:
        sessions = conn.execute(
            "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions ORDER BY id",
        ).fetchall()
        events = conn.execute(
            "SELECT session_id, ts, process FROM window_events ORDER BY session_id, ts, id",
        ).fetchall()
    if day:
        sessions = [row for row in sessions if str(row[1]).startswith(day)]
        keep = {row[0] for row in sessions}
        events = [row for row in events if row[0] in keep]
    end_at = until or now()
    total = 0.0
    switches = 0
    per: dict[str, float] = {}
    by_session: dict[int, list[tuple[str, str]]] = {}
    for sid, ts, process in events:
        by_session.setdefault(sid, []).append((ts, process))
    for sid, started, ended in sessions:
        ended = ended or end_at
        total += max(0.0, minutes(started, ended))
        rows = by_session.get(sid, [])
        switches += max(0, len(rows) - 1)
        for i, (ts, process) in enumerate(rows):
            stop = rows[i + 1][0] if i + 1 < len(rows) else ended
            name = (process or "未知")
            if name.lower().endswith(".exe"):
                name = name[:-4]
            per[name] = per.get(name, 0.0) + max(0.0, minutes(ts, stop))
    top = sorted(per.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {"分钟": round(total, 1), "切换": switches, "程序": top}


# ---- 快照 OCR 文字 / 复习提醒 ----

def add_frame_text(conn: sqlite3.Connection, path: str, ts: str, text: str,
                   session_id: int = 0) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO frame_text (path, ts, text, session_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET text = excluded.text, session_id = excluded.session_id",
            (path, ts, text, int(session_id or 0)),
        )
        conn.commit()
    core_db.index_row(conn, "frame", path, ts, text)


def frame_text_between(conn: sqlite3.Connection, ts_from: str, ts_to: str, limit: int = 60):
    """时间窗内的快照文字（按时间升序）—— 复盘拼「屏幕上的文字」用。"""
    with _LOCK:
        return conn.execute(
            "SELECT path, ts, text FROM frame_text "
            "WHERE ts >= ? AND ts <= ? ORDER BY ts LIMIT ?",
            (ts_from, ts_to, limit),
        ).fetchall()
