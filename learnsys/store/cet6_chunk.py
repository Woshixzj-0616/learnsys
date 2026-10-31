"""六级长句意群：候选长句与尝试流水。

题干/原文/词级时间轴都在试卷文件里，这里只记「哪一句、写了什么、得分」；
卡片仍写 `wrong_items`，复习仍由 `review_state` 排期。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

_COLUMNS = (
    "id, ts, paper_id, paper_title, section, item, sentence, expected, "
    "answer, score, missed_json, extra_json, duration_s, cards_added, chunk_count"
)


def chunk_candidates(conn: sqlite3.Connection, *, since: str,
                     limit: int = 60) -> list[dict]:
    """长句候选：A/B 段优先，有笔记的优先，最近高分通过的排后。"""
    limit = max(1, min(int(limit or 60), 300))
    with _LOCK:
        rows = conn.execute(
            "SELECT p.paper_id, p.paper_title, p.section, p.item, p.sentence, "
            "p.en, p.note, p.plays, p.updated_at "
            "FROM cet6_progress p "
            "WHERE length(p.en) >= 60 AND NOT EXISTS ("
            "  SELECT 1 FROM cet6_chunk_attempts a "
            "  WHERE a.paper_id = p.paper_id AND a.section = p.section "
            "  AND a.item = p.item AND a.sentence = p.sentence "
            "  AND a.score >= 0.9 AND a.ts >= ?) "
            "ORDER BY CASE WHEN p.section LIKE 'Section A%' THEN 0 "
            "              WHEN p.section LIKE 'Section B%' THEN 1 ELSE 2 END, "
            "         CASE WHEN p.note <> '' THEN 0 ELSE 1 END, "
            "         p.plays DESC, p.updated_at DESC, RANDOM() "
            "LIMIT ?",
            (since, limit)).fetchall()
    return [{
        "paper_id": row[0] or "",
        "paper_title": row[1] or "",
        "section": row[2] or "",
        "item": row[3] or "",
        "sentence": int(row[4] or 0),
        "en": row[5] or "",
        "note": row[6] or "",
        "plays": int(row[7] or 0),
        "updated_at": row[8] or "",
    } for row in rows]


def add_chunk_attempt(conn: sqlite3.Connection, *, paper_id: str,
                      paper_title: str = "", section: str = "", item: str = "",
                      sentence: int = 0, expected: str = "", answer: str = "",
                      score: float = 0, missed: list | None = None,
                      extra: list | None = None, duration_s: int = 0,
                      cards_added: int = 0, chunk_count: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO cet6_chunk_attempts "
            "(ts, paper_id, paper_title, section, item, sentence, expected, "
            " answer, score, missed_json, extra_json, duration_s, cards_added, "
            " chunk_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), paper_id, paper_title, section, item, int(sentence),
             expected, answer, float(score or 0),
             json.dumps(missed or [], ensure_ascii=False),
             json.dumps(extra or [], ensure_ascii=False),
             int(duration_s or 0), int(cards_added or 0),
             int(chunk_count or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def chunk_attempts(conn: sqlite3.Connection, *, since: str) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM cet6_chunk_attempts "
            "WHERE ts >= ? ORDER BY ts, id", (since,)).fetchall()
    return [{
        "id": int(row[0]), "ts": row[1] or "", "paper_id": row[2] or "",
        "paper_title": row[3] or "", "section": row[4] or "",
        "item": row[5] or "", "sentence": int(row[6] or 0),
        "expected": row[7] or "", "answer": row[8] or "",
        "score": float(row[9] or 0),
        "missed": json.loads(row[10] or "[]"),
        "extra": json.loads(row[11] or "[]"),
        "duration_s": int(row[12] or 0), "cards_added": int(row[13] or 0),
        "chunk_count": int(row[14] or 0),
    } for row in rows]
