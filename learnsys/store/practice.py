"""实践经验库：SQL 唯一落点。

三格（场景 / 坑 / 下次）+ 可选技术原因与证据；不做 FSRS，按搜索和最近用到取用。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now

_COLUMNS = (
    "id", "ts", "title", "scene", "pitfall", "next_time", "kind", "why",
    "evidence", "tags", "project_id", "source", "source_id", "used_count",
    "last_used", "status", "created_at", "updated_at",
)
_SELECT = ", ".join(_COLUMNS)
_UPDATABLE = (
    "title", "scene", "pitfall", "next_time", "kind", "why", "evidence",
    "tags", "project_id", "status",
)


def _row_dict(row) -> dict:
    out = dict(zip(_COLUMNS, row))
    for key in ("id", "project_id", "used_count"):
        out[key] = int(out.get(key) or 0)
    return out


def add_note(conn: sqlite3.Connection, *, title: str, scene: str = "",
             pitfall: str = "", next_time: str = "", kind: str = "pitfall",
             why: str = "", evidence: str = "", tags: str = "",
             project_id: int = 0, source: str = "manual",
             source_id: str = "") -> dict:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO practice_notes "
            "(ts, title, scene, pitfall, next_time, kind, why, evidence, tags, "
            " project_id, source, source_id, used_count, last_used, status, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', 'active', ?, ?)",
            (stamp, title, scene, pitfall, next_time, kind, why, evidence, tags,
             int(project_id or 0), source, source_id, stamp, stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_SELECT} FROM practice_notes WHERE id = ?",
            (cur.lastrowid,)).fetchone()
    return _row_dict(row)


def get_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_SELECT} FROM practice_notes WHERE id = ?",
            (int(note_id),)).fetchone()
    return _row_dict(row) if row else None


def update_note(conn: sqlite3.Connection, note_id: int,
                **fields) -> dict | None:
    sets: list[str] = []
    args: list = []
    for key in _UPDATABLE:
        if key not in fields:
            continue
        value = fields[key]
        sets.append(f"{key} = ?")
        args.append(int(value or 0) if key == "project_id" else value)
    if not sets:
        return get_note(conn, note_id)
    sets.append("updated_at = ?")
    args.extend([now(), int(note_id)])
    with _LOCK:
        conn.execute(
            f"UPDATE practice_notes SET {', '.join(sets)} WHERE id = ?", args)
        conn.commit()
        row = conn.execute(
            f"SELECT {_SELECT} FROM practice_notes WHERE id = ?",
            (int(note_id),)).fetchone()
    return _row_dict(row) if row else None


def list_notes(conn: sqlite3.Connection, *, query: str = "", tag: str = "",
               project_id: int = 0, status: str = "active",
               limit: int = 200) -> list[dict]:
    where = ["status = ?"]
    args: list = [status or "active"]
    text = str(query or "").strip()
    if text:
        like = f"%{text}%"
        where.append("(title LIKE ? OR scene LIKE ? OR pitfall LIKE ? "
                     "OR next_time LIKE ? OR why LIKE ? OR evidence LIKE ? "
                     "OR tags LIKE ?)")
        args.extend([like] * 7)
    tag = str(tag or "").strip()
    if tag:
        where.append("tags LIKE ?")
        args.append(f"%{tag}%")
    if int(project_id or 0):
        where.append("project_id = ?")
        args.append(int(project_id))
    args.append(max(1, min(int(limit or 200), 500)))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_SELECT} FROM practice_notes WHERE " + " AND ".join(where) +
            " ORDER BY updated_at DESC, id DESC LIMIT ?", args).fetchall()
    return [_row_dict(row) for row in rows]


def use_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    stamp = now()
    with _LOCK:
        conn.execute(
            "UPDATE practice_notes SET used_count = used_count + 1, "
            "last_used = ?, updated_at = ? WHERE id = ?",
            (stamp, stamp, int(note_id)))
        conn.commit()
        row = conn.execute(
            f"SELECT {_SELECT} FROM practice_notes WHERE id = ?",
            (int(note_id),)).fetchone()
    return _row_dict(row) if row else None


def archive_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    return update_note(conn, note_id, status="archived")


def delete_note(conn: sqlite3.Connection, note_id: int) -> bool:
    with _LOCK:
        cur = conn.execute(
            "DELETE FROM practice_notes WHERE id = ?", (int(note_id),))
        conn.commit()
        return bool(cur.rowcount)


def counts_by_project(conn: sqlite3.Connection) -> dict[int, int]:
    """每个项目下仍有效的经验条数；项目卡用。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT project_id, COUNT(*) FROM practice_notes "
            "WHERE status = 'active' AND project_id > 0 "
            "GROUP BY project_id").fetchall()
    return {int(project_id): int(count) for project_id, count in rows}
