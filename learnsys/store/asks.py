"""问答域：写入问答、最近问答、收藏问答的旧形状查询。"""
from __future__ import annotations

import sqlite3

from learnsys.core import db as core_db
from ._base import _LOCK, now


def add_ask(conn: sqlite3.Connection, question: str, answer: str, ms: int, backend: str,
            kind: str = "text", image_path: str = "", thread: str = "",
            starred: bool = False, conversation_id: int | None = None,
            first_ms: int | None = None) -> int:
    """记一次问答，返回这条的 id（收藏要用）。kind='image' 带框选图 | 'text' 纯文字；thread 分组同轮对话。

    `starred=True` 直接收进统一错题本 —— `asks.starred` 是 v1 历史列，不再写 1。
    """
    kind = "image" if kind == "image" else "text"
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO asks (ts, question, answer, ms, first_ms, backend, kind, "
            "image_path, thread, starred, provider, model, conversation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (stamp, question, answer, ms,
             None if first_ms is None else int(first_ms),
             backend, kind, image_path or "", thread or "",
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
def starred_asks(conn: sqlite3.Connection):
    """旧形状（ts, question, answer, kind, image_path, id）的收藏问答，兼容老调用。"""
    with _LOCK:
        return conn.execute(
            "SELECT a.ts, a.question, a.answer, a.kind, a.image_path, a.id "
            "FROM asks a JOIN wrong_items w "
            "  ON w.source = 'ask' AND w.source_id = 'ask:' || a.id "
            "ORDER BY a.id DESC").fetchall()
