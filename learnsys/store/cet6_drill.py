"""六级专项听写：候选句、单句读取、尝试流水。

这里只做“题库”和“练习记录”的 SQL；卡片仍写 `wrong_items`，
复习仍由 `review_state` 排期，不另建平行表。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

_PROGRESS_COLUMNS = (
    "paper_id, paper_title, section, item, sentence, en, note, plays, updated_at"
)


def _progress_dict(row) -> dict:
    return {
        "paper_id": row[0] or "",
        "paper_title": row[1] or "",
        "section": row[2] or "",
        "item": row[3] or "",
        "sentence": int(row[4] or 0),
        "en": row[5] or "",
        "note": row[6] or "",
        "plays": int(row[7] or 0),
        "updated_at": row[8] or "",
    }


def drill_candidates(conn: sqlite3.Connection, *, since: str,
                     limit: int = 40) -> list[dict]:
    """有笔记、且最近 3 天没以高分通过的句子；按播放次数优先。"""
    limit = max(1, min(int(limit or 40), 300))
    with _LOCK:
        rows = conn.execute(
            "SELECT p.paper_id, p.paper_title, p.section, p.item, p.sentence, "
            "p.en, p.note, p.plays, p.updated_at "
            "FROM cet6_progress p "
            "WHERE p.note <> '' AND NOT EXISTS ("
            "  SELECT 1 FROM cet6_drill_attempts a "
            "  WHERE a.paper_id = p.paper_id AND a.section = p.section "
            "  AND a.item = p.item AND a.sentence = p.sentence "
            "  AND a.score >= 0.9 AND a.ts >= ?) "
            "ORDER BY p.plays DESC, p.updated_at DESC, p.sentence LIMIT ?",
            (since, limit)).fetchall()
    return [_progress_dict(row) for row in rows]


def drill_coverage_candidates(conn: sqlite3.Connection, *, since: str,
                              limit: int = 20) -> list[dict]:
    """A/B 段里还没练过的句子：补齐长对话/短文理解的覆盖。"""
    limit = max(1, min(int(limit or 20), 200))
    with _LOCK:
        rows = conn.execute(
            "SELECT p.paper_id, p.paper_title, p.section, p.item, p.sentence, "
            "p.en, p.note, p.plays, p.updated_at "
            "FROM cet6_progress p "
            "WHERE (p.section LIKE 'Section A%' OR p.section LIKE 'Section B%') "
            "AND p.done = 0 AND p.plays < 3 AND p.note = '' AND NOT EXISTS ("
            "  SELECT 1 FROM cet6_drill_attempts a "
            "  WHERE a.paper_id = p.paper_id AND a.section = p.section "
            "  AND a.item = p.item AND a.sentence = p.sentence "
            "  AND a.ts >= ?) "
            "ORDER BY CASE WHEN EXISTS ("
            "  SELECT 1 FROM cet6_progress n WHERE n.paper_id = p.paper_id "
            "  AND n.note <> '') THEN 0 ELSE 1 END, RANDOM() LIMIT ?",
            (since, limit)).fetchall()
    return [_progress_dict(row) for row in rows]


def drill_sentence(conn: sqlite3.Connection, *, paper_id: str, section: str,
                   item: str, sentence: int) -> dict | None:
    """按主键取一句；服务端以库里的原文为准，不信客户端回传的 expected。"""
    with _LOCK:
        row = conn.execute(
            f"SELECT {_PROGRESS_COLUMNS} FROM cet6_progress "
            "WHERE paper_id = ? AND section = ? AND item = ? AND sentence = ?",
            (paper_id, section, item, int(sentence))).fetchone()
    return _progress_dict(row) if row else None


def add_drill_attempt(conn: sqlite3.Connection, *, paper_id: str,
                      paper_title: str = "", section: str = "", item: str = "",
                      sentence: int = 0, kind: str = "dictation",
                      expected: str = "", answer: str = "", score: float = 0,
                      missed: list | None = None, extra: list | None = None,
                      duration_s: int = 0, cards_added: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO cet6_drill_attempts "
            "(ts, paper_id, paper_title, section, item, sentence, kind, expected, "
            " answer, score, missed_json, extra_json, duration_s, cards_added) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), paper_id, paper_title, section, item, int(sentence), kind,
             expected, answer, float(score or 0),
             json.dumps(missed or [], ensure_ascii=False),
             json.dumps(extra or [], ensure_ascii=False),
             int(duration_s or 0), int(cards_added or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def drill_attempts(conn: sqlite3.Connection, *, since: str) -> list[dict]:
    """某天起的尝试流水；统计在 service 里算，store 只负责取数。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT id, ts, paper_id, paper_title, section, item, sentence, kind, "
            "expected, answer, score, missed_json, extra_json, duration_s, cards_added "
            "FROM cet6_drill_attempts WHERE ts >= ? ORDER BY ts, id",
            (since,)).fetchall()
    return [{
        "id": int(row[0]), "ts": row[1] or "", "paper_id": row[2] or "",
        "paper_title": row[3] or "", "section": row[4] or "",
        "item": row[5] or "", "sentence": int(row[6] or 0),
        "kind": row[7] or "dictation", "expected": row[8] or "",
        "answer": row[9] or "", "score": float(row[10] or 0),
        "missed": json.loads(row[11] or "[]"),
        "extra": json.loads(row[12] or "[]"),
        "duration_s": int(row[13] or 0), "cards_added": int(row[14] or 0),
    } for row in rows]
