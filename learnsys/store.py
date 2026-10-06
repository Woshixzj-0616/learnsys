"""本地 SQLite 存储：会话 + 前台窗口事件 + 声音转写。"""
from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
import threading

from learnsys import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);
CREATE TABLE IF NOT EXISTS window_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    process    TEXT,
    title      TEXT
);
CREATE INDEX IF NOT EXISTS idx_window_events_session ON window_events (session_id, ts);
CREATE TABLE IF NOT EXISTS transcripts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts_start   TEXT NOT NULL,
    ts_end     TEXT NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts (session_id, ts_start);
CREATE TABLE IF NOT EXISTS asks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    question TEXT NOT NULL,
    answer   TEXT NOT NULL,
    ms       INTEGER,
    backend  TEXT,
    kind     TEXT,          -- 'image' = 框了图再问 | 'text' = 纯文字问
    image_path TEXT,        -- 有图时 = 归档截图的路径；纯文字为空
    thread   TEXT           -- 同一轮对话（同一张图的追问）共用一个号，方便复盘
);
"""

_KIND_COLS = ("kind", "image_path", "thread")


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列（CREATE IF NOT EXISTS 不会给已存在的表加字段）。"""
    rows = conn.execute("PRAGMA table_info(asks)").fetchall()
    have = {row[1] for row in rows}
    for col in _KIND_COLS:
        if col not in have:
            conn.execute(f"ALTER TABLE asks ADD COLUMN {col} TEXT")
    conn.commit()

_LOCK = threading.Lock()


def connect(path=None) -> sqlite3.Connection:
    """注意：连接会被后台线程共用，所以关掉同线程检查，写操作用 _LOCK 串起来。"""
    target = pathlib.Path(path) if path else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


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


def add_transcript(conn: sqlite3.Connection, session_id: int, ts_start: str, ts_end: str, text: str) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO transcripts (session_id, ts_start, ts_end, text) VALUES (?, ?, ?, ?)",
            (session_id, ts_start, ts_end, text),
        )
        conn.commit()


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


def add_ask(conn: sqlite3.Connection, question: str, answer: str, ms: int, backend: str,
            kind: str = "text", image_path: str = "", thread: str = "") -> None:
    """记一次问答。kind='image' 带框选图（image_path=归档截图）| 'text' 纯文字；thread 分组同轮对话。"""
    kind = "image" if kind == "image" else "text"
    with _LOCK:
        conn.execute(
            "INSERT INTO asks (ts, question, answer, ms, backend, kind, image_path, thread) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), question, answer, ms, backend, kind, image_path or "", thread or ""),
        )
        conn.commit()


def recent_asks(conn: sqlite3.Connection, limit: int = 8):
    """最近问过的几条（新→旧）—— 带 kind/image_path，界面好区分「图问 / 文问」。"""
    with _LOCK:
        return conn.execute(
            "SELECT ts, question, answer, kind, image_path FROM asks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
