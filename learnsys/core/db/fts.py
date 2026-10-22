"""全文检索：FTS5 trigram 可用就走 MATCH，不可用自动退回 LIKE。"""
from __future__ import annotations

import sqlite3

from .connection import _LOCK
from .schema import FTS_SCHEMA


def _ensure_fts(conn: sqlite3.Connection) -> None:
    """FTS5 trigram 可用就用；不可用退回普通表（LIKE 查询）。"""
    try:
        conn.executescript(FTS_SCHEMA)
        return
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS search_idx "
        "(body TEXT, module TEXT, ref_id INTEGER, ts TEXT)")
    conn.commit()


def fts_ready(conn: sqlite3.Connection) -> bool:
    """查 sqlite_master 判断 search_idx 是不是 FTS5 虚表。

    ⚠️ 不能按 `id(conn)` 缓存：Python 的 id 会被回收复用，旧连接的结论
    会错误地套到新连接上。查一次 sqlite_master 很便宜，别省。
    """
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'search_idx'").fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row[0] and "fts5" in str(row[0]).lower())


def index_row(conn: sqlite3.Connection, module: str, ref_id, ts: str, body: str) -> None:
    """把一条记录写进检索索引（先删同一条，避免重复）。"""
    body = (body or "").strip()
    if not body:
        return
    try:
        with _LOCK:
            conn.execute("DELETE FROM search_idx WHERE module = ? AND ref_id = ?",
                         (module, ref_id))
            conn.execute(
                "INSERT INTO search_idx (body, module, ref_id, ts) VALUES (?, ?, ?, ?)",
                (body, module, ref_id, ts))
            conn.commit()
    except sqlite3.Error:
        pass          # 索引是锦上添花，失败不能拖垮写入


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """跨天检索。FTS 可用且关键词够长走 MATCH，否则退回 LIKE。

    trigram 对 3 字以上的中文片段最有效；两个字（如「栈」）走 LIKE 更稳。
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 20), 100))
    rows: list[tuple] = []
    if fts_ready(conn) and len(query) >= 3:
        try:
            rows = conn.execute(
                "SELECT module, ref_id, ts, body FROM search_idx "
                "WHERE search_idx MATCH ? ORDER BY rank LIMIT ?",
                (query, limit)).fetchall()
        except sqlite3.Error:
            rows = []
    if not rows:
        pattern = f"%{query}%"
        asks = conn.execute(
            "SELECT 'ask', id, ts, question || char(10) || answer FROM asks "
            "WHERE question LIKE ? OR answer LIKE ? ORDER BY ts DESC LIMIT ?",
            (pattern, pattern, limit)).fetchall()
        transcripts = conn.execute(
            "SELECT 'transcript', id, ts_start, text FROM transcripts "
            "WHERE text LIKE ? ORDER BY ts_start DESC LIMIT ?",
            (pattern, limit)).fetchall()
        frames = conn.execute(
            "SELECT 'frame', path, ts, text FROM frame_text "
            "WHERE text LIKE ? ORDER BY ts DESC LIMIT ?",
            (pattern, limit)).fetchall()
        rows = sorted(asks + transcripts + frames, key=lambda row: str(row[2]), reverse=True)[:limit]
    return [
        {"module": row[0], "ref_id": row[1], "ts": row[2], "text": str(row[3] or "")[:600]}
        for row in rows
    ]
