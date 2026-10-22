"""资料域：课件 / 笔记。原文在数据目录，正文存库，FTS 只是派生索引。"""
from __future__ import annotations

import json
import re
import sqlite3

from learnsys.core import db as core_db
from ._base import _LOCK, now


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
