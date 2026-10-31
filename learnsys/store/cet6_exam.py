"""六级真题自评：候选段、自评流水。

只存「练了哪一段、自评对几题、错了哪几题」；题干和音频仍在试卷 `data.js`，
这里不复制正文。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

_COLUMNS = (
    "id, ts, paper_id, paper_title, section, item, question_count, "
    "correct_count, wrong_json, duration_s"
)


def exam_candidates(conn: sqlite3.Connection, *, since: str,
                    limit: int = 40) -> list[dict]:
    """按段列出可练的真题：A/B 段优先，最近做过的排后，练得少的先上。"""
    limit = max(1, min(int(limit or 40), 200))
    with _LOCK:
        rows = conn.execute(
            "SELECT p.paper_id, p.paper_title, p.section, p.item, "
            "COUNT(*) AS sentences, MAX(e.ts) AS last_ts, COUNT(e.id) AS attempts "
            "FROM cet6_progress p "
            "LEFT JOIN cet6_exam_attempts e "
            "  ON e.paper_id = p.paper_id AND e.section = p.section "
            "  AND e.item = p.item "
            "GROUP BY p.paper_id, p.paper_title, p.section, p.item "
            "ORDER BY CASE WHEN p.section LIKE 'Section A%' THEN 0 "
            "              WHEN p.section LIKE 'Section B%' THEN 1 ELSE 2 END, "
            "         CASE WHEN MAX(e.ts) >= ? THEN 1 ELSE 0 END, "
            "         COUNT(e.id), RANDOM() "
            "LIMIT ?",
            (since, limit)).fetchall()
    return [{
        "paper_id": row[0] or "",
        "paper_title": row[1] or "",
        "section": row[2] or "",
        "item": row[3] or "",
        "sentences": int(row[4] or 0),
        "last_ts": row[5] or "",
        "attempts": int(row[6] or 0),
    } for row in rows]


def exam_item(conn: sqlite3.Connection, *, paper_id: str, section: str,
              item: str) -> dict | None:
    """确认这一段确实同步过；以库里的 `paper_title` 为准，不信客户端回传。"""
    with _LOCK:
        row = conn.execute(
            "SELECT paper_title, COUNT(*) FROM cet6_progress "
            "WHERE paper_id = ? AND section = ? AND item = ?",
            (paper_id, section, item)).fetchone()
    if not row or not int(row[1] or 0):
        return None
    return {"paper_title": row[0] or "", "sentences": int(row[1] or 0)}


def add_exam_attempt(conn: sqlite3.Connection, *, paper_id: str,
                     paper_title: str = "", section: str = "", item: str = "",
                     question_count: int, correct_count: int,
                     wrong: list[int] | None = None,
                     duration_s: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO cet6_exam_attempts "
            "(ts, paper_id, paper_title, section, item, question_count, "
            " correct_count, wrong_json, duration_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), paper_id, paper_title, section, item,
             int(question_count or 0), int(correct_count or 0),
             json.dumps(sorted({int(x) for x in (wrong or [])}), ensure_ascii=False),
             int(duration_s or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def exam_attempts(conn: sqlite3.Connection, *, since: str) -> list[dict]:
    """某天起的自评流水；统计在 service 里算。"""
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM cet6_exam_attempts "
            "WHERE ts >= ? ORDER BY ts, id", (since,)).fetchall()
    return [{
        "id": int(row[0]), "ts": row[1] or "", "paper_id": row[2] or "",
        "paper_title": row[3] or "", "section": row[4] or "",
        "item": row[5] or "", "question_count": int(row[6] or 0),
        "correct_count": int(row[7] or 0),
        "wrong": json.loads(row[8] or "[]"),
        "duration_s": int(row[9] or 0),
    } for row in rows]
