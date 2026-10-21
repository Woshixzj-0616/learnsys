"""本地 SQLite 存储：会话 + 前台窗口事件 + 声音转写。

v2 起真正的表结构在 `learnsys/core/db.py`；这里保留原有函数名，
让 app / record / liverec 不用一次性改完。写入时顺带维护全文索引。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
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
    """记一次问答，返回这条的 id（收藏要用）。kind='image' 带框选图 | 'text' 纯文字；thread 分组同轮对话。

    `starred=True` 直接收进统一错题本 —— `asks.starred` 是 v1 历史列，不再写 1。
    """
    kind = "image" if kind == "image" else "text"
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO asks (ts, question, answer, ms, backend, kind, image_path, thread, "
            "starred, provider, model, conversation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (stamp, question, answer, ms, backend, kind, image_path or "", thread or "",
             backend, backend, conversation_id),
        )
        row_id = int(cur.lastrowid or 0)
        if starred:
            conn.execute(
                "INSERT OR IGNORE INTO wrong_items "
                "(ts, source, source_id, question, answer, auto) "
                "VALUES (?, 'ask', ?, ?, ?, 0)",
                (stamp, f"ask:{row_id}", question, answer))
        conn.commit()
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


# ---- 统一错题本 ----
# 唯一来源是 wrong_items；asks.starred 只是 v1 的历史快照，迁移后不再读写。

WRONG_SOURCES = ("ask", "quiz", "cet6", "manual")

_WRONG_COLUMNS = (
    "id, ts, source, source_id, question, answer, my_answer, tags, note, "
    "auto, review_stage, last_review, mastered, material_id"
)


_QUESTION_NOISE = re.compile(
    r"[\s，。！？；：、“”‘’（）【】《》〈〉「」『』…—～·]+", re.UNICODE)


def wrong_fingerprint(question: str) -> str:
    """题目指纹：去空白/中文标点、转小写后哈希。

    只清中文标点和空白，**保留 `+ - * / = < >` 等数学符号** —— 否则
    「a+b」和「a-b」会撞成同一道题。
    """
    text = str(question or "")
    # 去掉题号前缀：「【第1题】」「第 2 题.」—— 自动工具和手动补收的题面才不会因前缀分家。
    text = re.sub(r"^\s*【\s*第\s*\d+\s*题\s*】", "", text)
    text = re.sub(r"^\s*第?\s*\d+\s*[题.、:：]\s*", "", text)
    cleaned = _QUESTION_NOISE.sub("", text).lower()
    return hashlib.sha1((cleaned or text).encode("utf-8")).hexdigest()[:16]


def _next_review(ts: str, last_review: str, stage: int) -> str:
    """下次复习日；练完 3 轮（stage=3）后返回空串。"""
    if stage >= len(REVIEW_INTERVALS):
        return ""
    base = str(last_review or ts)[:10]
    try:
        day = dt.date.fromisoformat(base)
    except ValueError:
        return ""
    return (day + dt.timedelta(days=REVIEW_INTERVALS[stage])).isoformat()


def _wrong_dict(row) -> dict:
    item = {
        "id": int(row[0]), "ts": row[1] or "", "source": row[2] or "manual",
        "source_id": row[3] or "", "question": row[4] or "", "answer": row[5] or "",
        "my_answer": row[6] or "", "tags": row[7] or "", "note": row[8] or "",
        "auto": bool(row[9]), "review_stage": int(row[10] or 0),
        "last_review": row[11] or "", "mastered": bool(row[12]),
        "material_id": int(row[13] or 0), "material_title": "",
    }
    item["next_review"] = _next_review(item["ts"], item["last_review"],
                                       item["review_stage"])
    return item


def add_wrong_item(conn: sqlite3.Connection, *, question: str, answer: str = "",
                   my_answer: str = "", tags: str = "", note: str = "",
                   source: str = "manual", source_id: str | None = None,
                   auto: bool = False, material_id: int = 0) -> tuple[int, bool]:
    """收一道错题；返回 (id, 是否新建)。同 source+source_id 只留第一条。"""
    question = str(question or "").strip()
    if not question:
        raise ValueError("错题的问题不能为空")
    source = source if source in WRONG_SOURCES else "manual"
    source_id = (str(source_id).strip() or None) if source_id else None
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO wrong_items "
            "(ts, source, source_id, question, answer, my_answer, tags, note, "
            "auto, material_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), source, source_id, question, str(answer or ""),
             str(my_answer or ""), str(tags or ""), str(note or ""),
             1 if auto else 0, int(material_id or 0)))
        created = cur.rowcount > 0
        item_id = int(cur.lastrowid or 0) if created else 0
        if not created and source_id:
            row = conn.execute(
                "SELECT id FROM wrong_items WHERE source = ? AND source_id = ?",
                (source, source_id)).fetchone()
            item_id = int(row[0]) if row else 0
        conn.commit()
    return item_id, created


def toggle_ask_wrong(conn: sqlite3.Connection, ask_id: int) -> bool:
    """问答「收藏 / 取消收藏」= 收进 / 移出统一错题本；返回新状态。"""
    source_id = f"ask:{int(ask_id)}"
    with _LOCK:
        row = conn.execute(
            "SELECT id FROM wrong_items WHERE source = 'ask' AND source_id = ?",
            (source_id,)).fetchone()
        if row is not None:
            conn.execute("DELETE FROM wrong_items WHERE id = ?", (int(row[0]),))
            conn.commit()
            return False
        ask = conn.execute(
            "SELECT ts, question, answer FROM asks WHERE id = ?",
            (int(ask_id),)).fetchone()
        if ask is None:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO wrong_items "
            "(ts, source, source_id, question, answer, auto) "
            "VALUES (?, 'ask', ?, ?, ?, 0)",
            (ask[0] or now(), source_id, ask[1] or "", ask[2] or ""))
        conn.commit()
        return True


def toggle_star(conn: sqlite3.Connection, ask_id: int) -> bool:
    """旧名字保留给快捷栏；语义已改为「收进 / 移出错题本」。"""
    return toggle_ask_wrong(conn, ask_id)


def _attach_material_titles(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    ids = sorted({int(item.get("material_id") or 0) for item in items} - {0})
    if not ids:
        return items
    marks = ",".join("?" for _ in ids)
    try:
        rows = conn.execute(
            f"SELECT id, title FROM materials WHERE id IN ({marks})", ids).fetchall()
    except sqlite3.Error:
        return items
    titles = {int(row[0]): row[1] or "" for row in rows}
    for item in items:
        item["material_title"] = titles.get(int(item.get("material_id") or 0), "")
    return items


def get_wrong_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
    if row is None:
        return None
    return _attach_material_titles(conn, [_wrong_dict(row)])[0]


def wrong_items(conn: sqlite3.Connection, *, status: str = "all",
                source: str = "", limit: int = 200, today=None,
                material_id: int = 0) -> list[dict]:
    """错题列表。status：due 待复习 / mastered 已掌握 / all 全部（含已掌握）。"""
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items ORDER BY ts DESC, id DESC"
        ).fetchall()
    today = str(today or dt.date.today().isoformat())[:10]
    items = [_wrong_dict(row) for row in rows]
    if source in WRONG_SOURCES:
        items = [item for item in items if item["source"] == source]
    if material_id:
        items = [item for item in items
                 if int(item.get("material_id") or 0) == int(material_id)]
    if status == "due":
        items = [item for item in items
                 if not item["mastered"] and item["next_review"]
                 and item["next_review"] <= today]
        items.sort(key=lambda item: item["next_review"])
    elif status == "mastered":
        items = [item for item in items if item["mastered"]]
    limit = max(1, min(int(limit or 200), 1000))
    return _attach_material_titles(conn, items[:limit])


def wrong_material_facets(conn: sqlite3.Connection) -> list[dict]:
    """错题本里有题的资料，用于「按资料筛选」。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT w.material_id, COALESCE(m.title, ''), COUNT(*) "
            "FROM wrong_items w LEFT JOIN materials m ON m.id = w.material_id "
            "WHERE w.material_id > 0 GROUP BY w.material_id "
            "ORDER BY COUNT(*) DESC, w.material_id DESC").fetchall()
    return [{"material_id": int(row[0]), "title": row[1] or "资料",
             "count": int(row[2] or 0)} for row in rows]


def wrong_due_items(conn: sqlite3.Connection, today=None) -> list[dict]:
    """到复习期的错题（启动提醒和页面共用这一个口径）。"""
    return wrong_items(conn, status="due", limit=1000, today=today)


def wrong_counts(conn: sqlite3.Connection, today=None) -> dict:
    day = str(today or dt.date.today().isoformat())[:10]
    with _LOCK:
        total, mastered, new_today = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(mastered), 0), "
            "COALESCE(SUM(ts LIKE ?), 0) FROM wrong_items",
            (f"{day}%",)).fetchone()
    return {"all": int(total or 0), "mastered": int(mastered or 0),
            "due": len(wrong_due_items(conn)), "new_today": int(new_today or 0)}


def review_wrong_item(conn: sqlite3.Connection, item_id: int, result: str) -> dict | None:
    """复习一次：remember 推进 1/3/7；forgot 打回明天重来。"""
    with _LOCK:
        row = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
        if row is None:
            return None
        item = _wrong_dict(row)
        stage = item["review_stage"]
        if result == "forgot":
            stage, mastered = 0, 0
        else:
            stage = min(stage + 1, len(REVIEW_INTERVALS))
            mastered = 1 if stage >= len(REVIEW_INTERVALS) else item["mastered"]
        conn.execute(
            "UPDATE wrong_items SET review_stage = ?, last_review = ?, mastered = ? "
            "WHERE id = ?",
            (stage, dt.date.today().isoformat(), mastered, int(item_id)))
        conn.commit()
        row = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
    return _wrong_dict(row) if row else None


def set_wrong_mastered(conn: sqlite3.Connection, item_id: int, mastered: bool) -> bool:
    """手动标记 / 取消掌握。取消后从明天重新复习，别卡在 7 天后的空档。"""
    with _LOCK:
        row = conn.execute(
            "SELECT review_stage FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
        if row is None:
            return False
        if mastered:
            conn.execute("UPDATE wrong_items SET mastered = 1 WHERE id = ?",
                         (int(item_id),))
        else:
            conn.execute(
                "UPDATE wrong_items SET mastered = 0, review_stage = 0, last_review = ? "
                "WHERE id = ?",
                (dt.date.today().isoformat(), int(item_id)))
        conn.commit()
        return True


def delete_wrong_item(conn: sqlite3.Connection, item_id: int) -> bool:
    with _LOCK:
        cur = conn.execute("DELETE FROM wrong_items WHERE id = ?", (int(item_id),))
        conn.commit()
        return bool(cur.rowcount)


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


REVIEW_INTERVALS = (1, 3, 7)   # 收录后第 1 / 3 / 7 天各复习一次


def starred_asks(conn: sqlite3.Connection):
    """旧形状（ts, question, answer, kind, image_path, id）的收藏问答，兼容老调用。"""
    with _LOCK:
        return conn.execute(
            "SELECT a.ts, a.question, a.answer, a.kind, a.image_path, a.id "
            "FROM asks a JOIN wrong_items w "
            "  ON w.source = 'ask' AND w.source_id = 'ask:' || a.id "
            "ORDER BY a.id DESC").fetchall()


def due_starred(conn: sqlite3.Connection, today) -> list[int]:
    """兼容旧名字：返回错题本条目 id（不是 ask id）。"""
    return [item["id"] for item in wrong_due_items(conn, today)]


def bump_review_stage(conn: sqlite3.Connection, item_ids: list[int]) -> None:
    """兼容旧名字：按「记住了」推进一轮。"""
    for item_id in item_ids or []:
        review_wrong_item(conn, int(item_id), "remember")


def add_event(conn: sqlite3.Connection, module: str, kind: str = "note",
              title: str = "", meta: dict | None = None, ref_id: int = 0) -> int:
    """写一条学习事件（时间线 / 复盘素材 / 插件统计共用）。"""
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO events (ts, module, kind, ref_id, title, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now(), str(module or "note"), str(kind or "note"), int(ref_id or 0),
             str(title or ""), json.dumps(meta or {}, ensure_ascii=False)))
        conn.commit()
        return int(cur.lastrowid or 0)


# ---- 资料库：课件 / 笔记 ----
# 原文在数据目录「资料库/原文」；正文存这张表，FTS 只是派生索引。

MATERIAL_KINDS = ("pdf", "docx", "pptx", "txt", "md", "note")

_MATERIAL_COLUMNS = (
    "id, title, kind, source, path, body, chars, pages, size, sha256, "
    "course, tags, status, meta_json, created_at, updated_at, last_opened"
)


def _material_dict(row, *, with_body: bool = False) -> dict:
    item = {
        "id": int(row[0]), "title": row[1] or "", "kind": row[2] or "note",
        "source": row[3] or "note", "path": row[4] or "",
        "chars": int(row[6] or 0), "pages": int(row[7] or 0),
        "size": int(row[8] or 0), "sha256": row[9] or "",
        "course": row[10] or "", "tags": row[11] or "",
        "status": row[12] or "active",
        "created_at": row[14] or "", "updated_at": row[15] or "",
        "last_opened": row[16] or "",
    }
    try:
        item["meta"] = json.loads(row[13] or "{}")
    except Exception:
        item["meta"] = {}
    if with_body:
        item["body"] = row[5] or ""
    else:
        item["preview"] = re.sub(r"\s+", " ", (row[5] or "").replace("\f", " ")).strip()[:160]
    return item


def add_material(conn: sqlite3.Connection, *, title: str, kind: str = "note",
                 source: str = "note", path: str = "", body: str = "",
                 pages: int = 0, size: int = 0, sha256: str | None = None,
                 course: str = "", tags: str = "",
                 meta: dict | None = None) -> tuple[int, bool]:
    """新增资料；有 sha256 且已存在时返回旧条目（不重复入库）。"""
    title = str(title or "").strip() or "未命名资料"
    kind = kind if kind in MATERIAL_KINDS else "note"
    body = str(body or "")
    if sha256:
        with _LOCK:
            row = conn.execute(
                "SELECT id FROM materials WHERE sha256 = ? AND status = 'active'",
                (sha256,)).fetchone()
        if row is not None:
            return int(row[0]), False
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO materials (title, kind, source, path, body, chars, "
            "pages, size, sha256, course, tags, status, meta_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (title, kind, source, path or "", body, len(body), int(pages or 0),
             int(size or 0), sha256, str(course or ""), str(tags or ""),
             json.dumps(meta or {}, ensure_ascii=False), stamp, stamp))
        created = cur.rowcount > 0
        item_id = int(cur.lastrowid or 0) if created else 0
        if not created and sha256:
            row = conn.execute(
                "SELECT id FROM materials WHERE sha256 = ? AND status = 'active'",
                (sha256,)).fetchone()
            item_id = int(row[0]) if row else 0
        conn.commit()
    if not created:
        return item_id, False
    core_db.index_row(conn, "material", item_id, stamp, f"{title}\n{body}")
    return item_id, True


def get_material(conn: sqlite3.Connection, item_id: int,
                 *, with_body: bool = True) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_MATERIAL_COLUMNS} FROM materials WHERE id = ?",
            (int(item_id),)).fetchone()
    return _material_dict(row, with_body=with_body) if row else None


def list_materials(conn: sqlite3.Connection, *, kind: str = "", course: str = "",
                   status: str = "active", limit: int = 200) -> list[dict]:
    where = []
    args: list = []
    if status in ("active", "trashed"):
        where.append("status = ?")
        args.append(status)
    if kind in MATERIAL_KINDS:
        where.append("kind = ?")
        args.append(kind)
    if course:
        where.append("course = ?")
        args.append(course)
    sql = f"SELECT {_MATERIAL_COLUMNS} FROM materials"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 200), 1000)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_material_dict(row) for row in rows]


def material_counts(conn: sqlite3.Connection) -> dict:
    with _LOCK:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM materials GROUP BY status").fetchall()
    counts = {str(status or ""): int(count or 0) for status, count in rows}
    return {"active": counts.get("active", 0), "trashed": counts.get("trashed", 0),
            "all": sum(counts.values())}


def update_material(conn: sqlite3.Connection, item_id: int, *,
                    title: str | None = None, body: str | None = None,
                    course: str | None = None, tags: str | None = None) -> dict | None:
    """改标题/正文/课程/标签；正文变了重算字数并重建索引。"""
    item = get_material(conn, item_id)
    if item is None:
        return None
    new_title = item["title"] if title is None else (str(title).strip() or item["title"])
    new_body = item["body"] if body is None else str(body)
    stamp = now()
    with _LOCK:
        conn.execute(
            "UPDATE materials SET title = ?, body = ?, chars = ?, course = ?, tags = ?, "
            "updated_at = ? WHERE id = ?",
            (new_title, new_body, len(new_body),
             item["course"] if course is None else str(course),
             item["tags"] if tags is None else str(tags),
             stamp, int(item_id)))
        conn.commit()
    core_db.index_row(conn, "material", int(item_id), stamp, f"{new_title}\n{new_body}")
    return get_material(conn, item_id)


def set_material_status(conn: sqlite3.Connection, item_id: int, status: str) -> bool:
    if status not in ("active", "trashed"):
        return False
    with _LOCK:
        cur = conn.execute(
            "UPDATE materials SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), int(item_id)))
        conn.commit()
    return bool(cur.rowcount)


def delete_material_row(conn: sqlite3.Connection, item_id: int) -> bool:
    """彻底删除记录 + 检索索引；原文文件由调用方删。"""
    with _LOCK:
        cur = conn.execute("DELETE FROM materials WHERE id = ?", (int(item_id),))
        try:
            conn.execute("DELETE FROM search_idx WHERE module = 'material' AND ref_id = ?",
                         (int(item_id),))
        except sqlite3.Error:
            pass
        conn.commit()
    return bool(cur.rowcount)


def touch_material(conn: sqlite3.Connection, item_id: int) -> None:
    with _LOCK:
        conn.execute("UPDATE materials SET last_opened = ? WHERE id = ?",
                     (now(), int(item_id)))
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
