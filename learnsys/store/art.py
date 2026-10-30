"""创作库：风格预设 `style_presets` + 作品档案 `art_works`。

只放 SQL 与行转换；图片路径是否安全、导入文本怎么解析在
`services/life/art.py`。删除预设只清作品引用，不删作品。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now

WORK_STATUSES = ("active", "archived")

_PRESET_COLUMNS = "id, name, prompt, negative, note, created_at, updated_at"
_WORK_COLUMNS = ("id, title, prompt, preset_id, model, file_path, note, status, "
                 "created_at, updated_at")
_PRESET_EDITABLE = ("name", "prompt", "negative", "note")
_WORK_EDITABLE = ("title", "prompt", "preset_id", "model", "file_path", "note")


def _preset_dict(row) -> dict:
    return {
        "id": int(row[0]), "name": row[1] or "",
        "prompt": row[2] or "", "negative": row[3] or "",
        "note": row[4] or "", "created_at": row[5] or "",
        "updated_at": row[6] or "",
    }


def _work_dict(row) -> dict:
    return {
        "id": int(row[0]), "title": row[1] or "", "prompt": row[2] or "",
        "preset_id": int(row[3] or 0), "model": row[4] or "",
        "file_path": row[5] or "", "note": row[6] or "",
        "status": row[7] or "active", "created_at": row[8] or "",
        "updated_at": row[9] or "",
    }


def _title(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("作品标题不能为空")
    return text


def _preset_name(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("风格名称不能为空")
    return text


# --------------------------------------------------------------- style_presets

def list_presets(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_PRESET_COLUMNS} FROM style_presets "
            "ORDER BY name, id LIMIT ?",
            (max(1, min(int(limit or 100), 500)),)).fetchall()
    return [_preset_dict(row) for row in rows]


def get_preset(conn: sqlite3.Connection, preset_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_PRESET_COLUMNS} FROM style_presets WHERE id = ?",
            (int(preset_id),)).fetchone()
    return _preset_dict(row) if row else None


def get_preset_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_PRESET_COLUMNS} FROM style_presets WHERE name = ?",
            (str(name or "").strip(),)).fetchone()
    return _preset_dict(row) if row else None


def upsert_preset(conn: sqlite3.Connection, *, name: str,
                  prompt: str = "", negative: str = "",
                  note: str = "") -> dict:
    """按 `name` 唯一键新增/更新。"""
    name = _preset_name(name)
    stamp = now()
    with _LOCK:
        conn.execute(
            "INSERT INTO style_presets "
            "(name, prompt, negative, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET prompt = excluded.prompt, "
            "negative = excluded.negative, note = excluded.note, "
            "updated_at = excluded.updated_at",
            (name, str(prompt or ""), str(negative or ""), str(note or ""),
             stamp, stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_PRESET_COLUMNS} FROM style_presets WHERE name = ?",
            (name,)).fetchone()
    return _preset_dict(row)


def update_preset(conn: sqlite3.Connection, preset_id: int,
                  **changes) -> dict | None:
    if changes.get("name") is not None:
        changes = dict(changes)
        changes["name"] = _preset_name(changes["name"])
    fields = [(key, str(changes[key])) for key in _PRESET_EDITABLE
              if key in changes and changes[key] is not None]
    if not fields:
        return get_preset(conn, preset_id)
    sets = ", ".join(f"{key} = ?" for key, _ in fields) + ", updated_at = ?"
    args = [value for _, value in fields] + [now(), int(preset_id)]
    with _LOCK:
        cur = conn.execute(f"UPDATE style_presets SET {sets} WHERE id = ?", args)
        conn.commit()
    return get_preset(conn, preset_id) if cur.rowcount else None


def delete_preset(conn: sqlite3.Connection, preset_id: int) -> dict | None:
    """删除预设，并把引用它的作品 `preset_id` 清零（作品不跟着删）。"""
    item = get_preset(conn, preset_id)
    if item is None:
        return None
    with _LOCK:
        conn.execute("UPDATE art_works SET preset_id = 0 WHERE preset_id = ?",
                     (int(preset_id),))
        conn.execute("DELETE FROM style_presets WHERE id = ?", (int(preset_id),))
        conn.commit()
    return item


# ------------------------------------------------------------------- art_works

def list_works(conn: sqlite3.Connection, *, status: str = "active",
               limit: int = 200) -> list[dict]:
    sql = f"SELECT {_WORK_COLUMNS} FROM art_works"
    args: list = []
    status = str(status or "")
    if status and status != "all":
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 200), 500)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_work_dict(row) for row in rows]


def get_work(conn: sqlite3.Connection, work_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_WORK_COLUMNS} FROM art_works WHERE id = ?",
            (int(work_id),)).fetchone()
    return _work_dict(row) if row else None


def add_work(conn: sqlite3.Connection, *, title: str, prompt: str = "",
             preset_id: int = 0, model: str = "", file_path: str = "",
             note: str = "") -> dict:
    title = _title(title)
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO art_works "
            "(title, prompt, preset_id, model, file_path, note, status, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (title, str(prompt or ""), int(preset_id or 0), str(model or ""),
             str(file_path or ""), str(note or ""), stamp, stamp))
        conn.commit()
        new_id = int(cur.lastrowid or 0)
    return get_work(conn, new_id)


def update_work(conn: sqlite3.Connection, work_id: int,
                **changes) -> dict | None:
    if changes.get("title") is not None:
        changes = dict(changes)
        changes["title"] = _title(changes["title"])
    fields = []
    for key in _WORK_EDITABLE:
        if key not in changes or changes[key] is None:
            continue
        value = changes[key]
        fields.append((key, int(value) if key == "preset_id" else str(value)))
    if not fields:
        return get_work(conn, work_id)
    sets = ", ".join(f"{key} = ?" for key, _ in fields) + ", updated_at = ?"
    args = [value for _, value in fields] + [now(), int(work_id)]
    with _LOCK:
        cur = conn.execute(f"UPDATE art_works SET {sets} WHERE id = ?", args)
        conn.commit()
    return get_work(conn, work_id) if cur.rowcount else None


def set_work_status(conn: sqlite3.Connection, work_id: int,
                    status: str) -> dict | None:
    status = str(status or "")
    if status not in WORK_STATUSES:
        raise ValueError("作品状态只能是 active / archived")
    with _LOCK:
        cur = conn.execute(
            "UPDATE art_works SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), int(work_id)))
        conn.commit()
    return get_work(conn, work_id) if cur.rowcount else None


def delete_work(conn: sqlite3.Connection, work_id: int) -> dict | None:
    item = get_work(conn, work_id)
    if item is None:
        return None
    with _LOCK:
        conn.execute("DELETE FROM art_works WHERE id = ?", (int(work_id),))
        conn.commit()
    return item
