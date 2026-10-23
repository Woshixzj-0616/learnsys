"""知识点与答题流水的 SQL 层。

BKT-ready 口径只在这里定义一次；P18.2 做 BKT 时必须复用 `BKT_READY_SQL`。
"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now

BKT_READY_SQL = (
    "a.source = 'quiz' AND a.correct IS NOT NULL "
    "AND a.points_source = 'model' AND a.parse_ok = 1"
)


def _point_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM knowledge_points WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else None


def all_points(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, kind, sort FROM knowledge_points "
        "WHERE active = 1 ORDER BY sort, id").fetchall()
    return [{"id": int(r[0]), "name": r[1], "kind": r[2], "sort": int(r[3])}
            for r in rows]


def point_by_id(conn: sqlite3.Connection, point_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, kind, sort FROM knowledge_points "
        "WHERE id = ? AND active = 1", (int(point_id),)).fetchone()
    if not row:
        return None
    return {"id": int(row[0]), "name": row[1], "kind": row[2], "sort": int(row[3])}


def add_attempt(conn: sqlite3.Connection, *, ts: str, day: str,
                conversation_id: int = 0, material_id: int = 0, question_no: int = 0,
                question_key: str = "", question: str, my_answer: str,
                correct: int | None, feedback: str = "", source: str = "quiz",
                points_source: str = "model", points_raw: str = "",
                parse_ok: int = 0, origin_key: str,
                points: list[str] | tuple[str, ...] = ()) -> tuple[int, bool]:
    """按 origin_key 幂等插入；返回 (attempt_id, 是否新建)。"""
    point_ids = [pid for name in points if (pid := _point_id(conn, name))]
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO quiz_attempts "
            "(ts, day, conversation_id, material_id, question_no, question_key, "
            " question, my_answer, correct, feedback, source, points_source, "
            " points_raw, parse_ok, origin_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, day, int(conversation_id or 0), int(material_id or 0),
             int(question_no or 0), str(question_key or ""), str(question),
             str(my_answer or ""), correct, str(feedback or ""), source,
             points_source, str(points_raw or ""), 1 if parse_ok else 0,
             str(origin_key)))
        created = cur.rowcount > 0
        if created:
            attempt_id = int(cur.lastrowid)
            for point_id in point_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO attempt_points (attempt_id, point_id) "
                    "VALUES (?, ?)", (attempt_id, point_id))
        else:
            row = conn.execute(
                "SELECT id FROM quiz_attempts WHERE origin_key = ?",
                (str(origin_key),)).fetchone()
            attempt_id = int(row[0]) if row else 0
        conn.commit()
    return attempt_id, created


def _where_day(start_day: str) -> tuple[str, tuple]:
    if start_day:
        return " AND a.day >= ?", (start_day,)
    return "", ()


def stats(conn: sqlite3.Connection, start_day: str = "") -> dict:
    """按类目统计；`bkt_ready` 只认 live + 判出对错 + model 标注 + 解析正常。"""
    where, args = _where_day(start_day)
    points = []
    for point in all_points(conn):
        row = conn.execute(
            "SELECT COUNT(*), "
            " SUM(CASE WHEN a.source = 'quiz' THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN a.source = 'quiz' AND a.correct IS NOT NULL THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN a.source = 'quiz' AND a.correct = 1 THEN 1 ELSE 0 END), "
            f" SUM(CASE WHEN {BKT_READY_SQL} THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN a.source = 'backfill' THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN a.points_source = 'fallback' THEN 1 ELSE 0 END), "
            " MAX(a.ts) "
            "FROM attempt_points ap JOIN quiz_attempts a ON a.id = ap.attempt_id "
            "WHERE ap.point_id = ?" + where,
            (point["id"], *args)).fetchone()
        attempts = int(row[0] or 0)
        quiz_attempts = int(row[1] or 0)
        known = int(row[2] or 0)
        correct = int(row[3] or 0)
        points.append({
            **point,
            "attempts": attempts,
            "quiz_attempts": quiz_attempts,
            "quiz_known": known,
            "quiz_correct": correct,
            "accuracy": round(correct / known, 4) if known else None,
            "bkt_ready": int(row[4] or 0),
            "backfill": int(row[5] or 0),
            "fallback": int(row[6] or 0),
            "last_ts": row[7] or "",
        })

    row = conn.execute(
        "SELECT COUNT(*), "
        " SUM(CASE WHEN a.source = 'quiz' THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.source = 'quiz' AND a.correct IS NOT NULL THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.source = 'quiz' AND a.correct = 1 THEN 1 ELSE 0 END), "
        f" SUM(CASE WHEN {BKT_READY_SQL} THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.source = 'backfill' THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.points_source = 'fallback' THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.source = 'quiz' AND a.parse_ok = 0 THEN 1 ELSE 0 END), "
        " SUM(CASE WHEN a.day = ? THEN 1 ELSE 0 END) "
        "FROM quiz_attempts a WHERE 1 = 1" + where,
        (day_today(), *args)).fetchone()
    attempts = int(row[0] or 0)
    known = int(row[2] or 0)
    correct = int(row[3] or 0)
    return {
        "points": points,
        "totals": {
            "attempts": attempts,
            "quiz_attempts": int(row[1] or 0),
            "quiz_known": known,
            "quiz_correct": correct,
            "accuracy": round(correct / known, 4) if known else None,
            "bkt_ready": int(row[4] or 0),
            "backfill": int(row[5] or 0),
            "fallback": int(row[6] or 0),
            "parse_failed": int(row[7] or 0),
            "today": int(row[8] or 0),
        },
    }


def day_today() -> str:
    return now()[:10]


def point_attempts(conn: sqlite3.Connection, point_id: int, limit: int = 20,
                   offset: int = 0, start_day: str = "") -> dict | None:
    point = point_by_id(conn, point_id)
    if not point:
        return None
    where, args = _where_day(start_day)
    count = conn.execute(
        "SELECT COUNT(*) FROM attempt_points ap "
        "JOIN quiz_attempts a ON a.id = ap.attempt_id "
        "WHERE ap.point_id = ?" + where, (int(point_id), *args)).fetchone()[0]
    rows = conn.execute(
        "SELECT a.id, a.ts, a.conversation_id, a.material_id, a.question_no, "
        "       a.question, a.my_answer, a.correct, a.feedback, a.source, "
        "       a.points_source, a.points_raw, a.parse_ok, "
        "       GROUP_CONCAT(kp.name, '、') "
        "FROM attempt_points ap "
        "JOIN quiz_attempts a ON a.id = ap.attempt_id "
        "LEFT JOIN attempt_points ap2 ON ap2.attempt_id = a.id "
        "LEFT JOIN knowledge_points kp ON kp.id = ap2.point_id "
        "WHERE ap.point_id = ?" + where +
        " GROUP BY a.id ORDER BY a.id DESC LIMIT ? OFFSET ?",
        (int(point_id), *args, int(limit), int(offset))).fetchall()
    items = []
    for row in rows:
        items.append({
            "id": int(row[0]), "ts": row[1] or "",
            "conversation_id": int(row[2] or 0), "material_id": int(row[3] or 0),
            "question_no": int(row[4] or 0), "question": row[5] or "",
            "my_answer": row[6] or "",
            "correct": None if row[7] is None else bool(row[7]),
            "feedback": row[8] or "", "source": row[9] or "quiz",
            "points_source": row[10] or "model", "points_raw": row[11] or "",
            "parse_ok": bool(row[12]),
            "points": [x for x in str(row[13] or "").split("、") if x],
        })
    return {"point": point, "count": int(count), "limit": int(limit),
            "offset": int(offset), "items": items}


def meta_value(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row[0] or "") if row else ""


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)))
        conn.commit()


def backfill_candidates(conn: sqlite3.Connection, before: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, source_id, question, answer, my_answer, tags, material_id "
        "FROM wrong_items WHERE source = 'quiz' AND ts < ? ORDER BY id",
        (before,)).fetchall()
    return [{
        "id": int(r[0]), "ts": r[1] or "", "source_id": r[2] or "",
        "question": r[3] or "", "answer": r[4] or "", "my_answer": r[5] or "",
        "tags": r[6] or "", "material_id": int(r[7] or 0),
    } for r in rows]


def has_live_attempt(conn: sqlite3.Connection, conversation_id: int,
                     question_key: str) -> bool:
    if not question_key:
        return False
    row = conn.execute(
        "SELECT 1 FROM quiz_attempts WHERE source = 'quiz' "
        "AND conversation_id = ? AND question_key = ? LIMIT 1",
        (int(conversation_id or 0), str(question_key))).fetchone()
    return row is not None


def attempt_exists(conn: sqlite3.Connection, origin_key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM quiz_attempts WHERE origin_key = ?", (origin_key,)).fetchone() is not None


def ready_attempts(conn: sqlite3.Connection, start_day: str = "") -> list[dict]:
    """P18.2 BKT 的唯一取数入口；不要另写 SQL。"""
    where, args = _where_day(start_day)
    rows = conn.execute(
        "SELECT a.id, a.ts, a.day, a.correct, GROUP_CONCAT(kp.name, '、') "
        "FROM quiz_attempts a JOIN attempt_points ap ON ap.attempt_id = a.id "
        "JOIN knowledge_points kp ON kp.id = ap.point_id "
        f"WHERE {BKT_READY_SQL}" + where +
        " GROUP BY a.id ORDER BY a.id", args).fetchall()
    return [{"id": int(r[0]), "ts": r[1], "day": r[2], "correct": bool(r[3]),
             "points": [x for x in str(r[4] or "").split("、") if x]} for r in rows]
