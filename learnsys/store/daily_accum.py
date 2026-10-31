"""每日积累：纠音池、当天条目与进度。

题干/原文/时间轴仍在试卷文件；这里只存展示所需字段和状态。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

_PRON_COLUMNS = (
    "id, paper_id, paper_title, section, item, sentence, target, heard_as, "
    "kind, note, status, attempts, first_seen, last_seen, last_used"
)
_ACCUM_COLUMNS = (
    "id, day, kind, ref_key, payload_json, status, created_at, updated_at"
)


def note_rows(conn: sqlite3.Connection) -> list[dict]:
    """精听里有笔记的句子；纠音解析的唯一输入。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT paper_id, paper_title, section, item, sentence, en, note, "
            "updated_at FROM cet6_progress WHERE note <> '' "
            "ORDER BY updated_at DESC, paper_id, section, item, sentence"
        ).fetchall()
    return [{
        "paper_id": row[0] or "", "paper_title": row[1] or "",
        "section": row[2] or "", "item": row[3] or "",
        "sentence": int(row[4] or 0), "en": row[5] or "",
        "note": row[6] or "", "updated_at": row[7] or "",
    } for row in rows]


def _pron_dict(row) -> dict:
    return {
        "id": int(row[0]), "paper_id": row[1] or "",
        "paper_title": row[2] or "", "section": row[3] or "",
        "item": row[4] or "", "sentence": int(row[5] or 0),
        "target": row[6] or "", "heard_as": row[7] or "",
        "kind": row[8] or "unknown", "note": row[9] or "",
        "status": row[10] or "new", "attempts": int(row[11] or 0),
        "first_seen": row[12] or "", "last_seen": row[13] or "",
        "last_used": row[14] or "",
    }


def pron_upsert(conn: sqlite3.Connection, *, paper_id: str,
                paper_title: str = "", section: str = "", item: str = "",
                sentence: int = 0, target: str, heard_as: str = "",
                kind: str = "unknown", note: str = "",
                seen_at: str = "") -> tuple[int, bool]:
    """同一个词在同一句里只留一条；再次出现只刷新时间/补充听成内容。"""
    stamp = str(seen_at or now())
    with _LOCK:
        row = conn.execute(
            "SELECT id, heard_as, kind FROM cet6_pron_items "
            "WHERE paper_id = ? AND section = ? AND item = ? AND sentence = ? "
            "AND target = ?",
            (paper_id, section, item, int(sentence), target)).fetchone()
        if row:
            item_id, old_heard, old_kind = int(row[0]), row[1] or "", row[2] or "unknown"
            conn.execute(
                "UPDATE cet6_pron_items SET last_seen = ?, note = ?, "
                "heard_as = ?, kind = ? WHERE id = ?",
                (stamp, note, heard_as or old_heard,
                 kind if kind != "unknown" else old_kind, item_id))
            conn.commit()
            return item_id, False
        cur = conn.execute(
            "INSERT INTO cet6_pron_items "
            "(paper_id, paper_title, section, item, sentence, target, heard_as, "
            " kind, note, status, attempts, first_seen, last_seen, last_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 0, ?, ?, '')",
            (paper_id, paper_title, section, item, int(sentence), target,
             heard_as, kind, note, stamp, stamp))
        conn.commit()
        return int(cur.lastrowid or 0), True


def pron_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_PRON_COLUMNS} FROM cet6_pron_items WHERE id = ?",
            (int(item_id),)).fetchone()
    return _pron_dict(row) if row else None


def pron_candidates(conn: sqlite3.Connection, *, since: str,
                    limit: int = 5) -> list[dict]:
    """还没掌握、最近没被每日卡用过；最近出现的优先。"""
    limit = max(1, min(int(limit or 5), 50))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_PRON_COLUMNS} FROM cet6_pron_items "
            "WHERE status <> 'mastered' AND (last_used = '' OR last_used < ?) "
            "ORDER BY last_seen DESC, id DESC LIMIT ?",
            (since, limit)).fetchall()
    return [_pron_dict(row) for row in rows]


def mark_pron_used(conn: sqlite3.Connection, ids: list[int], day: str) -> None:
    ids = [int(x) for x in ids or []]
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    with _LOCK:
        conn.execute(
            f"UPDATE cet6_pron_items SET last_used = ? WHERE id IN ({marks})",
            (str(day or "")[:10], *ids))
        conn.commit()


def set_pron_status(conn: sqlite3.Connection, item_id: int,
                    status: str) -> None:
    with _LOCK:
        conn.execute(
            "UPDATE cet6_pron_items SET status = ? WHERE id = ?",
            (status, int(item_id)))
        conn.commit()


def add_accum(conn: sqlite3.Connection, *, day: str, kind: str,
              ref_key: str, payload: dict) -> int:
    stamp = now()
    with _LOCK:
        conn.execute(
            "INSERT OR IGNORE INTO cet6_accum_items "
            "(day, kind, ref_key, payload_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'new', ?, ?)",
            (day, kind, ref_key,
             json.dumps(payload, ensure_ascii=False), stamp, stamp))
        row = conn.execute(
            "SELECT id FROM cet6_accum_items WHERE day = ? AND kind = ? "
            "AND ref_key = ?", (day, kind, ref_key)).fetchone()
        conn.commit()
    return int(row[0]) if row else 0


def _accum_dict(row) -> dict:
    try:
        payload = json.loads(row[4] or "{}")
    except ValueError:
        payload = {}
    return {
        "id": int(row[0]), "day": row[1] or "", "kind": row[2] or "",
        "ref_key": row[3] or "", "payload": payload if isinstance(payload, dict) else {},
        "status": row[5] or "new", "created_at": row[6] or "",
        "updated_at": row[7] or "",
    }


def accum_items(conn: sqlite3.Connection, day: str) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_ACCUM_COLUMNS} FROM cet6_accum_items WHERE day = ? "
            "ORDER BY kind, id", (str(day or "")[:10],)).fetchall()
    return [_accum_dict(row) for row in rows]


def accum_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_ACCUM_COLUMNS} FROM cet6_accum_items WHERE id = ?",
            (int(item_id),)).fetchone()
    return _accum_dict(row) if row else None


def set_accum_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    with _LOCK:
        conn.execute(
            "UPDATE cet6_accum_items SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), int(item_id)))
        conn.commit()


def set_all_accum_status(conn: sqlite3.Connection, day: str, status: str) -> int:
    """把当天还没动过的条目一次性标成已读；已掌握的不降级。"""
    with _LOCK:
        cur = conn.execute(
            "UPDATE cet6_accum_items SET status = ?, updated_at = ? "
            "WHERE day = ? AND status = 'new'",
            (status, now(), str(day or "")[:10]))
        conn.commit()
        return int(cur.rowcount or 0)


def accum_counts(conn: sqlite3.Connection, day: str) -> dict:
    with _LOCK:
        rows = conn.execute(
            "SELECT kind, COUNT(*), SUM(CASE WHEN status <> 'new' THEN 1 ELSE 0 END) "
            "FROM cet6_accum_items WHERE day = ? GROUP BY kind",
            (str(day or "")[:10],)).fetchall()
    return {row[0]: {"total": int(row[1] or 0), "done": int(row[2] or 0)}
            for row in rows}


def accum_days(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit or 30), 180))
    with _LOCK:
        rows = conn.execute(
            "SELECT day, COUNT(*), SUM(CASE WHEN status <> 'new' THEN 1 ELSE 0 END) "
            "FROM cet6_accum_items GROUP BY day ORDER BY day DESC LIMIT ?",
            (limit,)).fetchall()
    return [{"day": row[0], "total": int(row[1] or 0),
             "done": int(row[2] or 0)} for row in rows]
