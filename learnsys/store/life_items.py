"""生活事务箱：`life_items` 的 SQL 与行转换。

只做存储与状态落库；「能不能从 open 跳到 archived」这类判定在
`services/life/items.py`，路由层不写 SQL。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now

ITEM_KINDS = ("todo", "habit", "note")
ITEM_STATUSES = ("open", "done", "archived")

_COLUMNS = ("id, title, kind, due_date, status, note, value, done_at, "
            "created_at, updated_at")
_EDITABLE = ("title", "kind", "due_date", "note", "value")


def _item_dict(row) -> dict:
    return {
        "id": int(row[0]), "title": row[1] or "",
        "kind": row[2] or "todo", "due_date": row[3] or "",
        "status": row[4] or "open", "note": row[5] or "",
        "value": row[6] or "", "done_at": row[7] or "",
        "created_at": row[8] or "", "updated_at": row[9] or "",
    }


def _check_title(title) -> str:
    value = str(title or "").strip()
    if not value:
        raise ValueError("事务标题不能为空")
    return value


def _check_kind(kind) -> str:
    value = str(kind or "todo")
    if value not in ITEM_KINDS:
        raise ValueError("事务类型只能是 todo / habit / note")
    return value


def list_items(conn: sqlite3.Connection, *, status: str = "open",
               limit: int = 200) -> list[dict]:
    sql = f"SELECT {_COLUMNS} FROM life_items WHERE 1 = 1"
    args: list = []
    status = str(status or "")
    if status and status != "all":
        sql += " AND status = ?"
        args.append(status)
    sql += (" ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'done' THEN 1 "
            "ELSE 2 END, CASE WHEN due_date = '' THEN 1 ELSE 0 END, "
            "due_date, id DESC LIMIT ?")
    args.append(max(1, min(int(limit or 200), 1000)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_item_dict(row) for row in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM life_items WHERE id = ?",
            (int(item_id),)).fetchone()
    return _item_dict(row) if row else None


def add_item(conn: sqlite3.Connection, *, title: str, kind: str = "todo",
             due_date: str = "", note: str = "", value: str = "") -> dict:
    title = _check_title(title)
    kind = _check_kind(kind)
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO life_items "
            "(title, kind, due_date, status, note, value, done_at, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, '', ?, ?)",
            (title, kind, str(due_date or ""), str(note or ""),
             str(value or ""), stamp, stamp))
        conn.commit()
        new_id = int(cur.lastrowid or 0)
    return get_item(conn, new_id)


def update_item(conn: sqlite3.Connection, item_id: int,
                **changes) -> dict | None:
    if changes.get("title") is not None:
        changes = dict(changes)
        changes["title"] = _check_title(changes["title"])
    if changes.get("kind") is not None:
        changes = dict(changes)
        changes["kind"] = _check_kind(changes["kind"])
    fields = [(key, str(changes[key])) for key in _EDITABLE
              if key in changes and changes[key] is not None]
    if not fields:
        return get_item(conn, item_id)
    sets = ", ".join(f"{key} = ?" for key, _ in fields) + ", updated_at = ?"
    args = [value for _, value in fields] + [now(), int(item_id)]
    with _LOCK:
        cur = conn.execute(f"UPDATE life_items SET {sets} WHERE id = ?", args)
        conn.commit()
    return get_item(conn, item_id) if cur.rowcount else None


def set_status(conn: sqlite3.Connection, item_id: int, status: str,
               *, ts: str = "") -> dict | None:
    status = str(status or "")
    if status not in ITEM_STATUSES:
        raise ValueError("事务状态只能是 open / done / archived")
    stamp = str(ts or "") or now()
    with _LOCK:
        cur = conn.execute(
            "UPDATE life_items SET status = ?, done_at = ?, updated_at = ? "
            "WHERE id = ?",
            (status, stamp if status == "done" else "",
             stamp, int(item_id)))
        conn.commit()
    return get_item(conn, item_id) if cur.rowcount else None


def delete_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    item = get_item(conn, item_id)
    if item is None:
        return None
    with _LOCK:
        conn.execute("DELETE FROM life_items WHERE id = ?", (int(item_id),))
        conn.commit()
    return item


def due_items(conn: sqlite3.Connection, day: str,
              *, limit: int = 20) -> list[dict]:
    """今天及以前到期、仍未完成的事务；无期限的不算到期。"""
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM life_items "
            "WHERE status = 'open' AND due_date != '' AND due_date <= ? "
            "ORDER BY due_date, id LIMIT ?",
            (str(day)[:10], max(1, min(int(limit or 20), 100)))).fetchall()
    return [_item_dict(row) for row in rows]


def item_counts(conn: sqlite3.Connection, day: str) -> dict:
    with _LOCK:
        row = conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status = 'open' AND due_date != '' "
            "         AND due_date < ? THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) "
            "FROM life_items", (str(day)[:10],)).fetchone()
    return {"open": int(row[0] or 0), "overdue": int(row[1] or 0),
            "done": int(row[2] or 0)}
