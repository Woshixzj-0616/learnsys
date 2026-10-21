"""本地 SQLite 存储：会话 + 前台窗口事件 + 声音转写。

v2 起真正的表结构在 `learnsys/core/db.py`；这里保留原有函数名，
让 app / record / liverec 不用一次性改完。写入时顺带维护全文索引。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import threading

from learnsys import config
from learnsys.core import db as core_db

SCHEMA = core_db.SCHEMA

_LOCK = threading.Lock()


def connect(path=None) -> sqlite3.Connection:
    """注意：连接会被后台线程共用，所以关掉同线程检查，写操作用 _LOCK 串起来。"""
    return core_db.connect(path)


def _migrate(conn: sqlite3.Connection) -> None:
    """兼容旧调用：老库补列（真正的实现在 core.db）。"""
    core_db._migrate_columns(conn)


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
            kind: str = "text", image_path: str = "", thread: str = "",
            starred: bool = False, conversation_id: int | None = None) -> int:
    """记一次问答，返回这条的 id（收藏要用）。kind='image' 带框选图 | 'text' 纯文字；thread 分组同轮对话。"""
    kind = "image" if kind == "image" else "text"
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO asks (ts, question, answer, ms, backend, kind, image_path, thread, "
            "starred, provider, model, conversation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stamp, question, answer, ms, backend, kind, image_path or "", thread or "",
             1 if starred else 0, backend, backend, conversation_id),
        )
        conn.commit()
        row_id = int(cur.lastrowid or 0)
    core_db.index_row(conn, "ask", row_id, stamp, f"{question}\n{answer}")
    return row_id


def recent_asks(conn: sqlite3.Connection, limit: int = 8, day: str = "",
                with_conversation: bool = False):
    """最近问过的几条（新→旧）—— 带 kind/image_path/id，界面好区分图问/文问、好收藏。

    `day` 传 'YYYY-MM-DD' 就只取那天的；统一库下「今天的对话笔记」必须带它。
    `with_conversation=True` 时多带一列 conversation_id（Web 时间线跳会话用）；
    默认不带，横栏历史按旧 6 列形状解包。
    """
    extra = ", conversation_id" if with_conversation else ""
    with _LOCK:
        if day:
            return conn.execute(
                f"SELECT ts, question, answer, kind, image_path, id{extra} "
                "FROM asks WHERE ts LIKE ? ORDER BY id DESC LIMIT ?",
                (f"{day}%", limit),
            ).fetchall()
        return conn.execute(
            f"SELECT ts, question, answer, kind, image_path, id{extra} "
            "FROM asks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def toggle_star(conn: sqlite3.Connection, ask_id: int) -> bool:
    """收藏 / 取消收藏一条问答，返回新状态（True = 已收藏）。"""
    with _LOCK:
        row = conn.execute("SELECT starred FROM asks WHERE id = ?", (ask_id,)).fetchone()
        if row is None:
            return False
        new = 0 if row[0] else 1
        conn.execute("UPDATE asks SET starred = ? WHERE id = ?", (new, ask_id))
        conn.commit()
        return bool(new)


def starred_asks(conn: sqlite3.Connection):
    """收藏了的问答（新→旧）—— 错题本导出用。"""
    with _LOCK:
        return conn.execute(
            "SELECT ts, question, answer, kind, image_path, id FROM asks "
            "WHERE starred = 1 ORDER BY id DESC",
        ).fetchall()


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

def add_frame_text(conn: sqlite3.Connection, path: str, ts: str, text: str) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO frame_text (path, ts, text) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET text = excluded.text",
            (path, ts, text),
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


REVIEW_INTERVALS = (1, 3, 7)   # 收藏后第 1 / 3 / 7 天各提醒一次


def due_starred(conn: sqlite3.Connection, today) -> list[int]:
    """错题本里「到该复习的日子」的问答 id（第 1/3/7 天各提醒一次，提醒过就推进度）。"""
    rows = conn.execute(
        "SELECT id, ts, review_stage, COALESCE(last_remind, '') FROM asks "
        "WHERE starred = 1 ORDER BY id").fetchall()
    due = []
    for ask_id, ts, stage, last in rows:
        if stage >= len(REVIEW_INTERVALS):
            continue
        base = last or str(ts)[:10]
        try:
            base_day = dt.datetime.strptime(base[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - base_day).days >= REVIEW_INTERVALS[stage]:
            due.append(int(ask_id))
    return due

def bump_review_stage(conn: sqlite3.Connection, ask_ids: list[int]) -> None:
    if not ask_ids:
        return
    with _LOCK:
        conn.executemany(
            "UPDATE asks SET review_stage = review_stage + 1, last_remind = ? WHERE id = ?",
            [(dt.date.today().isoformat(), i) for i in ask_ids],
        )
        conn.commit()


# ---- v2 会话 / 消息（Web 工作台用）----

def create_conversation(conn: sqlite3.Connection, title: str = "",
                        module: str = "ask", mode: str = "explain") -> int:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO conversations (title, module, mode, started_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (title or "新对话", module, mode, stamp, stamp))
        conn.commit()
        return int(cur.lastrowid or 0)


def touch_conversation(conn: sqlite3.Connection, conversation_id: int,
                       title: str = "") -> None:
    with _LOCK:
        if title:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now(), conversation_id))
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now(), conversation_id))
        conn.commit()


def add_message(conn: sqlite3.Connection, conversation_id: int, role: str,
                content, ts: str = "") -> int:
    """content 可以是字符串或 dict/list；统一存 JSON。"""
    payload = content if isinstance(content, str) else json.dumps(
        content, ensure_ascii=False)
    stamp = ts or now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content_json, ts) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, role, payload, stamp))
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (stamp, conversation_id))
        conn.commit()
        return int(cur.lastrowid or 0)


def get_conversation(conn: sqlite3.Connection, conversation_id: int):
    with _LOCK:
        return conn.execute(
            "SELECT id, title, module, mode, summary, started_at, updated_at "
            "FROM conversations WHERE id = ?", (conversation_id,)).fetchone()


def list_conversations(conn: sqlite3.Connection, limit: int = 20,
                       module: str = "ask") -> list[dict]:
    """会话列表；`module` 默认只看问一问，插件内部会话（复盘/测验）不混进来。"""
    where, args = "", []
    if module:
        where = "WHERE c.module = ?"
        args.append(module)
    args.append(limit)
    with _LOCK:
        rows = conn.execute(
            "SELECT c.id, c.title, c.module, c.mode, c.started_at, c.updated_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) "
            f"FROM conversations c {where} ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
            args).fetchall()
    return [
        {"id": row[0], "title": row[1] or "", "module": row[2] or "ask",
         "mode": row[3] or "explain", "started_at": row[4] or "",
         "updated_at": row[5] or "", "messages": int(row[6] or 0)}
        for row in rows
    ]


def conversation_messages(conn: sqlite3.Connection, conversation_id: int) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT id, role, content_json, ts FROM messages "
            "WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
    out = []
    for row in rows:
        try:
            content = json.loads(row[2])
        except (json.JSONDecodeError, TypeError):
            content = row[2]
        out.append({"id": row[0], "role": row[1], "content": content, "ts": row[3]})
    return out
