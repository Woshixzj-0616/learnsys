"""复习调度域：review_state 是唯一状态，review_log 是历史。

错题/生词共用同一套 FSRS 状态；到期队列在 SQL 里直接联两张业务表。
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from ._base import _LOCK, now


def _next_review(ts: str, last_review: str, stage: int) -> str:
    """下次复习日；练完 3 轮（stage=3）后返回空串。"""
    if stage >= len(REVIEW_INTERVALS):
        return ""
    base = str(last_review or ts)[:10]
    try:
        day = dt.date.fromisoformat(base)
    except ValueError:
        return ""
    return (day + dt.timedelta(days=REVIEW_INTERVALS[stage])).isoformat()
def _attach_review_states(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """把 FSRS 状态贴到错题上；没有状态的保留旧 1/3/7 的回退值。"""
    if not items:
        return items
    ids = [item["id"] for item in items]
    placeholders = ",".join("?" * len(ids))
    with _LOCK:
        state_rows = conn.execute(
            "SELECT item_id, due, state, reps, lapses, scheduled_days "
            "FROM review_state WHERE item_type = 'wrong' "
            f"AND item_id IN ({placeholders})", ids).fetchall()
    states = {int(row[0]): row for row in state_rows}
    for item in items:
        state = states.get(item["id"])
        if state:
            item["next_review"] = state[1] or item["next_review"]
            item["review_state"] = state[2] or "new"
            item["review_reps"] = int(state[3] or 0)
            item["review_lapses"] = int(state[4] or 0)
            item["scheduled_days"] = int(state[5] or 0)
    return items
REVIEW_INTERVALS = (1, 3, 7)   # 收录后第 1 / 3 / 7 天各复习一次
# ---------------------------------------------------------------------------
# P14 复习调度：review_state 是唯一状态，review_log 是历史
# ---------------------------------------------------------------------------

REVIEW_ITEM_TYPES = ("wrong", "vocab")
_REVIEW_STATE_COLUMNS = (
    "item_type", "item_id", "state", "due", "stability", "difficulty",
    "reps", "lapses", "last_review", "scheduled_days", "elapsed_days",
    "updated_at",
)
_REVIEW_STATE_SELECT = ", ".join(_REVIEW_STATE_COLUMNS)


def _review_state_dict(row) -> dict:
    out = dict(zip(_REVIEW_STATE_COLUMNS, row))
    out["item_id"] = int(out.get("item_id") or 0)
    for key in ("reps", "lapses", "scheduled_days", "elapsed_days"):
        out[key] = int(out.get(key) or 0)
    for key in ("stability", "difficulty"):
        out[key] = float(out.get(key) or 0)
    return out


def get_review_state(conn: sqlite3.Connection, item_type: str,
                     item_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_REVIEW_STATE_SELECT} FROM review_state "
        "WHERE item_type = ? AND item_id = ?", (item_type, int(item_id))).fetchone()
    return _review_state_dict(row) if row else None


def save_review_state(conn: sqlite3.Connection, item_type: str, item_id: int,
                      *, state: str, due: str, stability: float = 0,
                      difficulty: float = 0, reps: int = 0, lapses: int = 0,
                      last_review: str = "", scheduled_days: int = 0,
                      elapsed_days: int = 0) -> dict:
    stamp = now()
    with _LOCK:
        conn.execute(
            "INSERT INTO review_state "
            "(item_type, item_id, state, due, stability, difficulty, reps, lapses, "
            " last_review, scheduled_days, elapsed_days, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(item_type, item_id) DO UPDATE SET "
            "state=excluded.state, due=excluded.due, stability=excluded.stability, "
            "difficulty=excluded.difficulty, reps=excluded.reps, "
            "lapses=excluded.lapses, last_review=excluded.last_review, "
            "scheduled_days=excluded.scheduled_days, "
            "elapsed_days=excluded.elapsed_days, updated_at=excluded.updated_at",
            (item_type, int(item_id), state, due, float(stability or 0),
             float(difficulty or 0), int(reps or 0), int(lapses or 0),
             last_review or "", int(scheduled_days or 0), int(elapsed_days or 0),
             stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_REVIEW_STATE_SELECT} FROM review_state "
            "WHERE item_type = ? AND item_id = ?", (item_type, int(item_id))).fetchone()
    return _review_state_dict(row)


def add_review_log(conn: sqlite3.Connection, *, item_type: str, item_id: int,
                   rating: int, state_before: str = "", due_before: str = "",
                   due_after: str = "", stability: float = 0,
                   difficulty: float = 0, elapsed_days: int = 0,
                   scheduled_days: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO review_log "
            "(ts, item_type, item_id, rating, state_before, due_before, due_after, "
            " stability, difficulty, elapsed_days, scheduled_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), item_type, int(item_id), int(rating), state_before or "",
             due_before or "", due_after or "", float(stability or 0),
             float(difficulty or 0), int(elapsed_days or 0),
             int(scheduled_days or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def seed_review_states(conn: sqlite3.Connection, today=None) -> int:
    """把旧 1/3/7 错题转成 FSRS 初始状态；幂等。"""
    day = str(today or dt.date.today().isoformat())[:10]
    rows = conn.execute(
        "SELECT w.id, w.ts, w.review_stage, w.last_review, w.mastered "
        "FROM wrong_items w LEFT JOIN review_state r "
        "ON r.item_type = 'wrong' AND r.item_id = w.id "
        "WHERE r.item_id IS NULL").fetchall()
    seeded = 0
    for row in rows:
        item_id, ts, stage, last_review, mastered = row
        if mastered:
            continue
        stage = int(stage or 0)
        # 新收的错题明天再出现，别在刚答错时立刻催复习（沿用旧版行为）
        due = _next_review(ts, last_review or "", stage) or day
        stability = max(1.0, float(REVIEW_INTERVALS[stage - 1])) if stage else 1.0
        save_review_state(
            conn, "wrong", int(item_id),
            state="new" if stage == 0 else "review", due=due,
            stability=stability, difficulty=5.0, reps=stage, lapses=0,
            last_review=str(last_review or ""),
            scheduled_days=int(stability) if stage else 0, elapsed_days=0)
        seeded += 1
    vocab_rows = conn.execute(
        "SELECT v.id FROM vocab_items v LEFT JOIN review_state r "
        "ON r.item_type = 'vocab' AND r.item_id = v.id "
        "WHERE r.item_id IS NULL AND v.status = 'active'").fetchall()
    for (item_id,) in vocab_rows:
        save_review_state(
            conn, "vocab", int(item_id), state="new", due=day, stability=1.0,
            difficulty=5.0, reps=0, lapses=0, last_review="",
            scheduled_days=0, elapsed_days=0)
        seeded += 1
    return seeded


def _review_join_sql() -> str:
    return (
        "SELECT r.item_type, r.item_id, r.state, r.due, r.stability, r.difficulty, "
        "r.reps, r.lapses, r.last_review, r.scheduled_days, "
        "w.question, w.answer, w.my_answer, w.tags, w.note, w.material_id, "
        "v.word, v.meaning, v.context, v.paper_title "
        "FROM review_state r "
        "LEFT JOIN wrong_items w ON r.item_type = 'wrong' AND w.id = r.item_id "
        "LEFT JOIN vocab_items v ON r.item_type = 'vocab' AND v.id = r.item_id ")


def _review_card(row) -> dict:
    item = {
        "item_type": row[0], "item_id": int(row[1]), "state": row[2],
        "due": row[3] or "", "stability": float(row[4] or 0),
        "difficulty": float(row[5] or 0), "reps": int(row[6] or 0),
        "lapses": int(row[7] or 0), "last_review": row[8] or "",
        "scheduled_days": int(row[9] or 0),
        "question": row[10] or "", "answer": row[11] or "",
        "my_answer": row[12] or "", "tags": row[13] or "", "note": row[14] or "",
        "material_id": int(row[15] or 0),
        "word": row[16] or "", "meaning": row[17] or "",
        "context": row[18] or "", "paper_title": row[19] or "",
    }
    item["title"] = item["question"] if item["item_type"] == "wrong" else item["word"]
    return item


def due_review_items(conn: sqlite3.Connection, *, limit: int = 50,
                     today=None, item_type: str = "") -> list[dict]:
    day = str(today or dt.date.today().isoformat())[:10]
    where = [
        "r.due <= ?",
        "(r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0))",
        "(r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active'))",
    ]
    args: list = [day]
    if item_type in REVIEW_ITEM_TYPES:
        where.insert(0, "r.item_type = ?")
        args.insert(0, item_type)
    sql = (_review_join_sql() + "WHERE " + " AND ".join(where)
           + " ORDER BY r.due, r.item_type, r.item_id LIMIT ?")
    args.append(max(1, min(int(limit or 50), 500)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_review_card(row) for row in rows]


def review_stats(conn: sqlite3.Connection, today=None, item_type: str = "") -> dict:
    day = str(today or dt.date.today().isoformat())[:10]
    filtered = item_type in REVIEW_ITEM_TYPES
    type_sql = " AND item_type = ?" if filtered else ""
    type_args = [item_type] if filtered else []
    join_filter = " AND r.item_type = ?" if filtered else ""
    join_args = [item_type] if filtered else []
    with _LOCK:
        total = conn.execute(
            "SELECT count(*) FROM review_state WHERE 1=1" + type_sql,
            type_args).fetchone()[0]
        new = conn.execute(
            "SELECT count(*) FROM review_state WHERE state = 'new'" + type_sql,
            type_args).fetchone()[0]
        reviewed = conn.execute(
            "SELECT count(*) FROM review_log WHERE substr(ts, 1, 10) = ?" + type_sql,
            [day, *type_args]).fetchone()[0]
        next_row = conn.execute(
            _review_join_sql() + "WHERE r.due > ? "
            "AND (r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0)) "
            "AND (r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active')) "
            + join_filter + " ORDER BY r.due LIMIT 1",
            [day, *join_args]).fetchone()
    due = len(due_review_items(conn, limit=500, today=day, item_type=item_type))
    return {"due": due, "new": int(new or 0), "total": int(total or 0),
            "reviewed_today": int(reviewed or 0),
            "next_due": (next_row[3] if next_row else "") or ""}


def recent_review_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT id, ts, item_type, item_id, rating, state_before, due_before, "
            "due_after, stability, difficulty, elapsed_days, scheduled_days "
            "FROM review_log ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit or 20), 200)),)).fetchall()
    return [{
        "id": row[0], "ts": row[1], "item_type": row[2], "item_id": int(row[3]),
        "rating": int(row[4]), "state_before": row[5] or "",
        "due_before": row[6] or "", "due_after": row[7] or "",
        "stability": float(row[8] or 0), "difficulty": float(row[9] or 0),
        "elapsed_days": int(row[10] or 0), "scheduled_days": int(row[11] or 0),
    } for row in rows]
