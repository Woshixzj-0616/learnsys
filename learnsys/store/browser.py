"""浏览记录域：只存 URL / 标题 / 域名 / 时间，不存正文、Cookie、截图。"""
from __future__ import annotations

import datetime
import sqlite3

from ._base import _LOCK, now


def add_browser_event(conn: sqlite3.Connection, *, tab_id: str, url: str,
                      title: str = "", domain: str = "") -> int | None:
    """同一 tab 连续的 URL + 标题不变就不重复写；返回新行 id 或 None。"""
    url = str(url or "").strip()
    title = str(title or "").strip()
    if not url:
        return None
    with _LOCK:
        row = conn.execute(
            "SELECT url, title FROM browser_events WHERE tab_id = ? "
            "ORDER BY id DESC LIMIT 1", (str(tab_id or ""),)).fetchone()
        if row is not None and str(row[0]) == url and str(row[1]) == title:
            return None
        cur = conn.execute(
            "INSERT INTO browser_events (ts, tab_id, url, title, domain) "
            "VALUES (?, ?, ?, ?, ?)",
            (now(), str(tab_id or ""), url, title, str(domain or "").lower()))
        conn.commit()
        return int(cur.lastrowid or 0)


def list_browser_events(conn: sqlite3.Connection, *, limit: int = 100,
                        days: int = 30, domain: str = "") -> list[dict]:
    """新 → 旧；days<=0 表示不限。"""
    clauses: list[str] = []
    params: list = []
    if days and int(days) > 0:
        cutoff = (datetime.datetime.now()
                  - datetime.timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
        clauses.append("ts >= ?")
        params.append(cutoff)
    domain = str(domain or "").strip().lower()
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit = max(1, min(200, int(limit or 100)))
    rows = conn.execute(
        f"SELECT id, ts, tab_id, url, title, domain FROM browser_events{where} "
        "ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    return [
        {"id": row[0], "ts": row[1], "tab_id": row[2], "url": row[3],
         "title": row[4], "domain": row[5]}
        for row in rows
    ]


def clear_browser_events(conn: sqlite3.Connection) -> int:
    with _LOCK:
        cur = conn.execute("DELETE FROM browser_events")
        conn.commit()
        return int(cur.rowcount or 0)


def cleanup_browser_events(conn: sqlite3.Connection, days: int) -> int:
    """删掉早于 `days` 天的记录；days<=0 不删。"""
    days = int(days or 0)
    if days <= 0:
        return 0
    cutoff = (datetime.datetime.now()
              - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        cur = conn.execute("DELETE FROM browser_events WHERE ts < ?", (cutoff,))
        conn.commit()
        return int(cur.rowcount or 0)
