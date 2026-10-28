"""每日简报域：一天一份 `briefings` + 条目 `briefing_items`。

写操作统一走 `_LOCK`；对外返回 dict，不返回 sqlite3.Row。
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from ._base import _LOCK, now

STATUSES = ("pending", "running", "ready", "partial", "failed")
CATEGORIES = ("politics", "world", "ai", "hardware", "internet",
              "health", "science", "energy", "space", "other")

_BRIEFING_COLUMNS = (
    "id, day, status, title, intro, item_count, model, source_stats_json, "
    "error, created_at, updated_at"
)
_ITEM_COLUMNS = (
    "id, briefing_id, category, title, title_zh, summary, url, url_key, "
    "source, published_at, rank, read_at, starred, meta_json, created_at"
)


def _briefing_dict(row) -> dict:
    item = {
        "id": int(row[0]), "day": row[1] or "", "status": row[2] or "pending",
        "title": row[3] or "", "intro": row[4] or "",
        "item_count": int(row[5] or 0), "model": row[6] or "",
        "error": row[8] or "", "created_at": row[9] or "",
        "updated_at": row[10] or "",
    }
    try:
        item["source_stats"] = json.loads(row[7] or "{}")
    except Exception:
        item["source_stats"] = {}
    return item


def _item_dict(row) -> dict:
    item = {
        "id": int(row[0]), "briefing_id": int(row[1] or 0),
        "category": row[2] or "other", "title": row[3] or "",
        "title_zh": row[4] or "", "summary": row[5] or "",
        "url": row[6] or "", "url_key": row[7] or "",
        "source": row[8] or "", "published_at": row[9] or "",
        "rank": int(row[10] or 0), "read_at": row[11] or "",
        "starred": bool(row[12]), "read": bool(row[11]),
        "created_at": row[14] or "",
    }
    try:
        item["meta"] = json.loads(row[13] or "{}")
    except Exception:
        item["meta"] = {}
    return item


def get_day(conn: sqlite3.Connection, day: str, *,
            with_items: bool = True) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_BRIEFING_COLUMNS} FROM briefings WHERE day = ?",
            (str(day),)).fetchone()
        if row is None:
            return None
        item = _briefing_dict(row)
        if with_items:
            rows = conn.execute(
                f"SELECT {_ITEM_COLUMNS} FROM briefing_items "
                "WHERE briefing_id = ? ORDER BY rank, id",
                (item["id"],)).fetchall()
            item["items"] = [_item_dict(row) for row in rows]
        return item


def list_days(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit or 30), 200))
    with _LOCK:
        rows = conn.execute(
            "SELECT day, status, title, item_count, error, updated_at "
            "FROM briefings ORDER BY day DESC LIMIT ?", (limit,)).fetchall()
    return [{"day": row[0] or "", "status": row[1] or "",
             "title": row[2] or "", "item_count": int(row[3] or 0),
             "error": row[4] or "", "updated_at": row[5] or ""}
            for row in rows]


def create_day(conn: sqlite3.Connection, day: str) -> tuple[int, bool]:
    """建当天占位行；已存在时返回既有 id。"""
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO briefings (day, status, created_at, updated_at) "
            "VALUES (?, 'pending', ?, ?)", (str(day), stamp, stamp))
        created = cur.rowcount > 0
        if created:
            briefing_id = int(cur.lastrowid or 0)
        else:
            row = conn.execute("SELECT id FROM briefings WHERE day = ?",
                               (str(day),)).fetchone()
            briefing_id = int(row[0]) if row else 0
        conn.commit()
    return briefing_id, created


def claim(conn: sqlite3.Connection, day: str, *,
          force: bool = False) -> int | None:
    """原子认领：pending/failed 可抢；force 时 ready/partial 也可重生成。"""
    allowed = ["pending", "failed"]
    if force:
        allowed += ["ready", "partial"]
    marks = ",".join("?" for _ in allowed)
    with _LOCK:
        row = conn.execute(
            f"UPDATE briefings SET status = 'running', updated_at = ? "
            f"WHERE day = ? AND status IN ({marks}) RETURNING id",
            (now(), str(day), *allowed)).fetchone()
        conn.commit()
    return int(row[0]) if row else None


def finish(conn: sqlite3.Connection, briefing_id: int, *, status: str,
           title: str = "", intro: str = "", model: str = "",
           source_stats: dict | None = None, error: str = "",
           item_count: int | None = None) -> None:
    status = status if status in STATUSES else "failed"
    fields = {
        "status": status,
        "title": str(title or ""),
        "intro": str(intro or ""),
        "model": str(model or ""),
        "source_stats_json": json.dumps(source_stats or {}, ensure_ascii=False),
        "error": str(error or ""),
        "updated_at": now(),
    }
    if item_count is not None:
        fields["item_count"] = int(item_count)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with _LOCK:
        conn.execute(f"UPDATE briefings SET {assignments} WHERE id = ?",
                     [*fields.values(), int(briefing_id)])
        conn.commit()


def save_items(conn: sqlite3.Connection, briefing_id: int,
               items: list[dict]) -> int:
    """整体替换条目；同 url_key 的已读/收藏保留。"""
    briefing_id = int(briefing_id)
    with _LOCK:
        rows = conn.execute(
            "SELECT url_key, read_at, starred FROM briefing_items "
            "WHERE briefing_id = ?", (briefing_id,)).fetchall()
        keep = {row[0]: (row[1] or "", int(row[2] or 0)) for row in rows}
        conn.execute("DELETE FROM briefing_items WHERE briefing_id = ?",
                     (briefing_id,))
        stamp = now()
        payload = []
        for index, item in enumerate(items):
            url_key = str(item.get("url_key") or "")
            read_at, starred = keep.get(url_key, ("", 0))
            payload.append((
                briefing_id, str(item.get("category") or "other"),
                str(item.get("title") or ""), str(item.get("title_zh") or ""),
                str(item.get("summary") or ""), str(item.get("url") or ""),
                url_key, str(item.get("source") or ""),
                str(item.get("published_at") or ""), int(index),
                read_at, int(starred),
                json.dumps(item.get("meta") or {}, ensure_ascii=False), stamp,
            ))
        if payload:
            conn.executemany(
                "INSERT INTO briefing_items "
                "(briefing_id, category, title, title_zh, summary, url, url_key, "
                " source, published_at, rank, read_at, starred, meta_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", payload)
        conn.commit()
    return len(payload)


def get_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_ITEM_COLUMNS} FROM briefing_items WHERE id = ?",
            (int(item_id),)).fetchone()
    return _item_dict(row) if row else None


def update_item(conn: sqlite3.Connection, item_id: int, *,
                read: bool | None = None, starred: bool | None = None) -> dict | None:
    fields: dict = {}
    if read is not None:
        fields["read_at"] = now() if read else ""
    if starred is not None:
        fields["starred"] = 1 if starred else 0
    if not fields:
        return get_item(conn, item_id)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with _LOCK:
        conn.execute(f"UPDATE briefing_items SET {assignments} WHERE id = ?",
                     [*fields.values(), int(item_id)])
        conn.commit()
    return get_item(conn, item_id)


def read_all(conn: sqlite3.Connection, day: str) -> int:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "UPDATE briefing_items SET read_at = ? "
            "WHERE read_at = '' AND briefing_id IN "
            "(SELECT id FROM briefings WHERE day = ?)", (stamp, str(day)))
        conn.commit()
    return int(cur.rowcount or 0)


def recent_seen(conn: sqlite3.Connection, days: int = 3,
                before_day: str = "") -> list[dict]:
    """最近 N 天的 url_key / 标题，用于跨天去重。

    `before_day` 用来排除正在重生成的那一天：否则当天旧条目会把自己过滤掉。
    """
    cutoff = (dt.datetime.now() - dt.timedelta(days=max(1, int(days)))
              ).strftime("%Y-%m-%d")
    where = "b.day >= ?"
    args: list = [cutoff]
    if before_day:
        where += " AND b.day < ?"
        args.append(str(before_day))
    with _LOCK:
        rows = conn.execute(
            "SELECT i.url_key, i.title FROM briefing_items i "
            f"JOIN briefings b ON b.id = i.briefing_id WHERE {where}",
            args).fetchall()
    return [{"url_key": row[0] or "", "title": row[1] or ""} for row in rows]


def recover_stale(conn: sqlite3.Connection, minutes: int = 10) -> int:
    """进程重启后，把卡住的 running 置为 failed，允许重新生成。"""
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=max(1, int(minutes)))
              ).strftime("%Y-%m-%d %H:%M:%S")
    with _LOCK:
        cur = conn.execute(
            "UPDATE briefings SET status = 'failed', error = ?, updated_at = ? "
            "WHERE status = 'running' AND updated_at < ?",
            ("后台重启，简报生成中断，请重试", now(), cutoff))
        conn.commit()
    return int(cur.rowcount or 0)
