"""生词统一表：按词全局去重；复习状态由 review 模块提供。"""
from __future__ import annotations

import datetime as dt
import sqlite3

from ._base import _LOCK, now
from .review import get_review_state, save_review_state


# ---------------------------------------------------------------------------
# P13 生词统一表：按词全局去重（与旧 localStorage 行为一致）
# ---------------------------------------------------------------------------

_VOCAB_COLUMNS = (
    "id", "word", "normalized", "meaning", "phonetic", "context",
    "paper_id", "paper_title", "sentence", "source", "status",
    "created_at", "updated_at",
)
_VOCAB_SELECT = ", ".join(_VOCAB_COLUMNS)


def _vocab_dict(row) -> dict:
    out = dict(zip(_VOCAB_COLUMNS, row))
    out["sentence"] = int(out.get("sentence") or 0)
    return out


def _normalize_word(word: str) -> str:
    return " ".join(str(word or "").strip().lower().split())


def _clip(value, cap: int) -> str:
    return str(value or "").strip()[:cap]


def add_vocab(conn: sqlite3.Connection, *, word: str, meaning: str = "",
              phonetic: str = "", context: str = "", paper_id: str = "",
              paper_title: str = "", sentence: int = 0,
              source: str = "cet6") -> tuple[dict, bool]:
    """加一个生词；同词（忽略大小写/空白）已存在时只补空字段。

    返回 `(item, created)`；不覆盖已有释义——用户手填的内容优先。
    """
    word = _clip(word, 200)
    if not word:
        raise ValueError("单词不能为空")
    normalized = _normalize_word(word)
    stamp = now()
    incoming = {
        "meaning": _clip(meaning, 1000),
        "phonetic": _clip(phonetic, 100),
        "context": _clip(context, 1000),
        "paper_id": _clip(paper_id, 200),
        "paper_title": _clip(paper_title, 200),
    }
    created = False
    with _LOCK:
        row = conn.execute(
            f"SELECT {_VOCAB_SELECT} FROM vocab_items WHERE normalized = ?",
            (normalized,)).fetchone()
        if row is not None:
            item = _vocab_dict(row)
            updates = {key: value for key, value in incoming.items()
                       if value and not item.get(key)}
            try:
                wanted_sentence = int(sentence or 0)
            except (TypeError, ValueError):
                wanted_sentence = 0
            if wanted_sentence and not item["sentence"]:
                updates["sentence"] = wanted_sentence
            if updates:
                updates["updated_at"] = stamp
                assignments = ", ".join(f"{key}=?" for key in updates)
                conn.execute(
                    f"UPDATE vocab_items SET {assignments} WHERE id = ?",
                    [*updates.values(), item["id"]])
                conn.commit()
                row = conn.execute(
                    f"SELECT {_VOCAB_SELECT} FROM vocab_items WHERE id = ?",
                    (item["id"],)).fetchone()
                item = _vocab_dict(row)
        else:
            cur = conn.execute(
                "INSERT INTO vocab_items "
                "(word, normalized, meaning, phonetic, context, paper_id, paper_title, "
                " sentence, source, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (word, normalized, incoming["meaning"], incoming["phonetic"],
                 incoming["context"], incoming["paper_id"], incoming["paper_title"],
                 int(sentence or 0), str(source or "cet6")[:20], stamp, stamp))
            conn.commit()
            row = conn.execute(
                f"SELECT {_VOCAB_SELECT} FROM vocab_items WHERE id = ?",
                (cur.lastrowid,)).fetchone()
            item = _vocab_dict(row)
            created = True

    # 新词明天进复习队列；老词没有卡就今天补上（幂等）
    if get_review_state(conn, "vocab", item["id"]) is None:
        due = (dt.date.today() + dt.timedelta(days=1 if created else 0)).isoformat()
        save_review_state(
            conn, "vocab", item["id"], state="new", due=due, stability=1.0,
            difficulty=5.0, reps=0, lapses=0, last_review="",
            scheduled_days=0, elapsed_days=0)
    return item, created


def list_vocab(conn: sqlite3.Connection, *, query: str = "", limit: int = 200,
               offset: int = 0, status: str = "active") -> dict:
    where = "status = ?"
    args: list = [status or "active"]
    text = str(query or "").strip()
    if text:
        where += " AND (word LIKE ? OR meaning LIKE ? OR context LIKE ?)"
        like = f"%{text}%"
        args.extend([like, like, like])
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    with _LOCK:
        total = conn.execute(
            f"SELECT count(*) FROM vocab_items WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_VOCAB_SELECT} FROM vocab_items WHERE {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall()
    items = _attach_vocab_review(conn, [_vocab_dict(row) for row in rows])
    return {"items": items, "count": int(total)}


def _attach_vocab_review(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """把 FSRS 状态贴到生词上（到期日、复习次数、遗忘次数）。"""
    if not items:
        return items
    ids = [item["id"] for item in items]
    placeholders = ",".join("?" * len(ids))
    with _LOCK:
        rows = conn.execute(
            "SELECT item_id, due, state, reps, lapses, scheduled_days "
            "FROM review_state WHERE item_type = 'vocab' "
            f"AND item_id IN ({placeholders})", ids).fetchall()
    states = {int(row[0]): row for row in rows}
    for item in items:
        state = states.get(item["id"])
        if state:
            item["next_review"] = state[1] or ""
            item["review_state"] = state[2] or "new"
            item["review_reps"] = int(state[3] or 0)
            item["review_lapses"] = int(state[4] or 0)
            item["scheduled_days"] = int(state[5] or 0)
    return items


def get_vocab(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_VOCAB_SELECT} FROM vocab_items WHERE id = ?", (item_id,)).fetchone()
    return _attach_vocab_review(conn, [_vocab_dict(row)])[0] if row else None


def update_vocab(conn: sqlite3.Connection, item_id: int, **fields) -> dict | None:
    allowed = {}
    for key in ("meaning", "phonetic", "status"):
        if key not in fields:
            continue
        value = fields[key]
        if value is None:
            continue
        if key == "status":
            if value not in ("active", "archived"):
                raise ValueError("状态只能是 active 或 archived")
            allowed[key] = value
        else:
            allowed[key] = _clip(value, 1000 if key == "meaning" else 100)
    if not allowed:
        return get_vocab(conn, item_id)
    allowed["updated_at"] = now()
    assignments = ", ".join(f"{key}=?" for key in allowed)
    with _LOCK:
        conn.execute(f"UPDATE vocab_items SET {assignments} WHERE id = ?",
                     [*allowed.values(), item_id])
        conn.commit()
    return get_vocab(conn, item_id)


def delete_vocab(conn: sqlite3.Connection, item_id: int) -> bool:
    with _LOCK:
        cur = conn.execute("DELETE FROM vocab_items WHERE id = ?", (item_id,))
        conn.execute(
            "DELETE FROM review_state WHERE item_type = 'vocab' AND item_id = ?",
            (item_id,))
        conn.commit()
    return bool(cur.rowcount)


def import_vocab(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    """导入旧 localStorage 生词（`{word,meaning,context,paper,at}`）。幂等。"""
    added = merged = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        word = str(row.get("word") or "").strip()
        if not word:
            continue
        _, created = add_vocab(
            conn, word=word,
            meaning=str(row.get("meaning") or ""),
            context=str(row.get("context") or ""),
            paper_title=str(row.get("paper") or row.get("paper_title") or ""),
            source="cet6")
        if created:
            added += 1
        else:
            merged += 1
    return {"added": added, "merged": merged}


def export_vocab(conn: sqlite3.Connection, status: str = "active") -> list[dict]:
    return list_vocab(conn, limit=500, status=status)["items"]
