"""问答反馈：答对 / 答偏 / 资料不对，按 run_id 挂在一次运行上。"""
from __future__ import annotations

import sqlite3

from ._base import _LOCK, now

VERDICTS = ("ok", "off", "source")


def add_qa_feedback(conn: sqlite3.Connection, run_id: str, verdict: str,
                    note: str = "") -> int:
    run_id = str(run_id or "").strip()
    verdict = str(verdict or "").strip()
    if not run_id:
        raise ValueError("run_id 不能为空")
    if verdict not in VERDICTS:
        raise ValueError(f"未知反馈类型：{verdict}")
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO qa_feedback (run_id, verdict, note, ts) "
            "VALUES (?, ?, ?, ?)",
            (run_id, verdict, " ".join(str(note or "").split())[:500], now()))
        conn.commit()
        return int(cur.lastrowid or 0)


def list_qa_feedback(conn: sqlite3.Connection, run_id: str = "",
                     limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit or 50), 200))
    with _LOCK:
        if run_id:
            rows = conn.execute(
                "SELECT id, run_id, verdict, note, ts FROM qa_feedback "
                "WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                (str(run_id), limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, run_id, verdict, note, ts FROM qa_feedback "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": row[0], "run_id": row[1], "verdict": row[2],
             "note": row[3] or "", "ts": row[4] or ""} for row in rows]
