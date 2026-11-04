"""记忆导入批次与抽取断点：记录封存档案、抽取进度和缺失来源。"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

_JSON_FIELDS = {"stats_json", "missing_json", "facts_json"}


def _dump(name: str, value) -> str:
    if isinstance(value, str):
        return value
    default = [] if name in {"missing_json", "facts_json"} else {}
    return json.dumps(value if value is not None else default,
                      ensure_ascii=False)


def _prep(fields: dict) -> dict:
    out = dict(fields)
    for key in _JSON_FIELDS:
        if key in out:
            out[key] = _dump(key, out[key])
    return out


def _row(row) -> dict:
    return {
        "id": int(row[0]), "kind": row[1] or "", "status": row[2] or "",
        "archive_id": row[3] or "", "archive_path": row[4] or "",
        "cutoff_at": row[5] or "", "body_sha256": row[6] or "",
        "file_sha256": row[7] or "", "stats_json": row[8] or "{}",
        "missing_json": row[9] or "[]", "error": row[10] or "",
        "started_at": row[11] or "", "finished_at": row[12] or "",
    }


def create_batch(conn: sqlite3.Connection, kind: str, **fields) -> int:
    values = {"kind": kind, "status": fields.pop("status", "running"),
              "started_at": fields.pop("started_at", now())}
    values.update(_prep(fields))
    keys = list(values)
    with _LOCK:
        cur = conn.execute(
            f"INSERT INTO memory_batches ({', '.join(keys)}) "
            f"VALUES ({', '.join('?' for _ in keys)})",
            [values[key] for key in keys])
        conn.commit()
        return int(cur.lastrowid or 0)


def update_batch(conn: sqlite3.Connection, batch_id: int, **fields) -> None:
    if not fields:
        return
    fields = _prep(fields)
    keys = list(fields)
    params = [fields[key] for key in keys] + [int(batch_id)]
    with _LOCK:
        conn.execute(
            f"UPDATE memory_batches SET {', '.join(f'{key} = ?' for key in keys)} "
            "WHERE id = ?", params)
        conn.commit()


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            "SELECT id, kind, status, archive_id, archive_path, cutoff_at, "
            "body_sha256, file_sha256, stats_json, missing_json, error, "
            "started_at, finished_at FROM memory_batches WHERE id = ?",
            (int(batch_id),)).fetchone()
    return _row(row) if row else None


def find_sealed(conn: sqlite3.Connection, kind: str) -> dict | None:
    with _LOCK:
        row = conn.execute(
            "SELECT id, kind, status, archive_id, archive_path, cutoff_at, "
            "body_sha256, file_sha256, stats_json, missing_json, error, "
            "started_at, finished_at FROM memory_batches "
            "WHERE kind = ? AND status = 'sealed' ORDER BY id DESC LIMIT 1",
            (kind,)).fetchone()
    return _row(row) if row else None


def add_chunk(conn: sqlite3.Connection, batch_id: int, chunk_key: str,
              source: str = "", session_ids: str = "") -> int:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO memory_extract_chunks "
            "(batch_id, chunk_key, source, session_ids, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (int(batch_id), chunk_key, source, session_ids, stamp, stamp))
        conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = conn.execute(
            "SELECT id FROM memory_extract_chunks WHERE chunk_key = ?",
            (chunk_key,)).fetchone()
        return int(row[0]) if row else 0


def update_chunk(conn: sqlite3.Connection, chunk_key: str, **fields) -> None:
    if not fields:
        return
    if "facts_json" in fields:
        fields["facts_json"] = _dump("facts_json", fields["facts_json"])
    fields["updated_at"] = now()
    keys = list(fields)
    with _LOCK:
        conn.execute(
            f"UPDATE memory_extract_chunks SET "
            f"{', '.join(f'{key} = ?' for key in keys)} WHERE chunk_key = ?",
            [fields[key] for key in keys] + [str(chunk_key)])
        conn.commit()


def done_chunk_keys(conn: sqlite3.Connection) -> set[str]:
    """所有批次里已经成功抽过的块；跨批次去重，保证续跑不重复花钱。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT chunk_key FROM memory_extract_chunks WHERE status = 'done'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def list_chunks(conn: sqlite3.Connection, batch_id: int,
                status: str = "") -> list[dict]:
    sql = ("SELECT id, batch_id, chunk_key, source, session_ids, status, "
           "facts_json, error, created_at, updated_at "
           "FROM memory_extract_chunks WHERE batch_id = ?")
    params: list = [int(batch_id)]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id"
    with _LOCK:
        rows = conn.execute(sql, params).fetchall()
    return [{"id": int(row[0]), "batch_id": int(row[1]),
             "chunk_key": row[2] or "", "source": row[3] or "",
             "session_ids": row[4] or "", "status": row[5] or "",
             "facts_json": row[6] or "[]", "error": row[7] or "",
             "created_at": row[8] or "", "updated_at": row[9] or ""}
            for row in rows]
