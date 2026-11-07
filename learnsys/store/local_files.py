"""本机文件索引：SQL 唯一落点。

表在 `core/db/schema_local_files.py`：`local_files` 存文件元数据，
`local_file_roots` 存每个白名单目录的扫描状态。正文不在这里。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK

_UPSERT = """
INSERT INTO local_files
    (root, path, name, name_l, path_l, ext, size, mtime_ns, indexed_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    root       = excluded.root,
    name       = excluded.name,
    name_l     = excluded.name_l,
    path_l     = excluded.path_l,
    ext        = excluded.ext,
    size       = excluded.size,
    mtime_ns   = excluded.mtime_ns,
    indexed_at = excluded.indexed_at
"""


def upsert_entries(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """一批文件元数据 upsert；一次提交，调用方按小批次循环。"""
    if not rows:
        return
    with _LOCK:
        conn.executemany(_UPSERT, rows)
        conn.commit()


def delete_unseen(conn: sqlite3.Connection, root: str, indexed_at: str) -> int:
    """删除本轮没扫到的旧行；扫描被截断时调用方不得调用。"""
    with _LOCK:
        cur = conn.execute(
            "DELETE FROM local_files WHERE root = ? AND indexed_at <> ?",
            (root, indexed_at))
        conn.commit()
        return int(cur.rowcount or 0)


def delete_root(conn: sqlite3.Connection, root: str) -> None:
    """白名单移除某个目录：文件行与状态行一起清。"""
    with _LOCK:
        conn.execute("DELETE FROM local_files WHERE root = ?", (root,))
        conn.execute("DELETE FROM local_file_roots WHERE root = ?", (root,))
        conn.commit()


def put_root_status(conn: sqlite3.Connection, root: str, *, scanned_at: str,
                    file_count: int, status: str, note: str = "") -> None:
    with _LOCK:
        conn.execute(
            """INSERT INTO local_file_roots
                   (root, scanned_at, file_count, status, note)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(root) DO UPDATE SET
                   scanned_at = excluded.scanned_at,
                   file_count = excluded.file_count,
                   status     = excluded.status,
                   note       = excluded.note""",
            (root, scanned_at, int(file_count), status, note))
        conn.commit()


def root_statuses(conn: sqlite3.Connection) -> dict[str, dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT root, scanned_at, file_count, status, note "
            "FROM local_file_roots ORDER BY root").fetchall()
    out: dict[str, dict] = {}
    for root, scanned_at, file_count, status, note in rows:
        out[str(root)] = {
            "root": str(root),
            "scanned_at": str(scanned_at or ""),
            "file_count": int(file_count or 0),
            "status": str(status or "ok"),
            "note": str(note or ""),
        }
    return out


def root_status(conn: sqlite3.Connection, root: str) -> dict | None:
    return root_statuses(conn).get(str(root))


def _like(text: str) -> str:
    """把用户输入当字面量：`%` / `_` / `\\` 不当通配符。"""
    escaped = (text.replace("\\", "\\\\")
                   .replace("%", "\\%")
                   .replace("_", "\\_"))
    return f"%{escaped}%"


def search(conn: sqlite3.Connection, tokens: list[str], suffix: str = "",
           limit: int = 10) -> tuple[list[tuple], int, int]:
    """按文件名 / 路径匹配；返回 (行, 索引总数, 命中总数)。

    打分与原内存实现一致：文件名全等 0、前缀 1、文件名全含 2、仅路径含 3，
    同分按修改时间倒序。
    """
    where: list[str] = []
    params: list[object] = []
    if suffix:
        where.append("ext = ?")
        params.append(suffix)
    for token in tokens:
        where.append("(name_l LIKE ? ESCAPE '\\' OR path_l LIKE ? ESCAPE '\\')")
        like = _like(token)
        params.extend([like, like])

    sql = "SELECT path, name_l, size, mtime_ns FROM local_files"
    if where:
        sql += " WHERE " + " AND ".join(where)
    where_params = list(params)

    order: list[str] = []
    order_params: list[object] = []
    if tokens:
        order.append(
            "CASE WHEN name_l = ? THEN 0 "
            "WHEN name_l LIKE ? ESCAPE '\\' THEN 1 "
            "WHEN " + " AND ".join(["name_l LIKE ? ESCAPE '\\'"] * len(tokens)) +
            " THEN 2 ELSE 3 END")
        order_params.append(" ".join(tokens))
        order_params.append(tokens[0].replace("\\", "\\\\")
                            .replace("%", "\\%").replace("_", "\\_") + "%")
        order_params.extend([_like(token) for token in tokens])
    order.append("mtime_ns DESC")
    sql += " ORDER BY " + ", ".join(order) + " LIMIT ?"
    params.extend(order_params)
    params.append(max(1, int(limit or 10)))

    count_sql = "SELECT COUNT(*) FROM local_files"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    with _LOCK:
        rows = conn.execute(sql, params).fetchall()
        matched = int(conn.execute(count_sql, where_params).fetchone()[0] or 0)
        total = int(conn.execute(
            "SELECT COUNT(*) FROM local_files").fetchone()[0] or 0)
    return [tuple(row) for row in rows], total, matched
