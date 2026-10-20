"""数据接口：今日、检索、错题本、配置、六级上下文。"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException

from learnsys import store
from learnsys.agent.config import load_config
from learnsys.core import db as core_db
from learnsys.server.security import require_token

router = APIRouter()


def _conn():
    """测试里可以 monkeypatch 这个函数，换成临时库。"""
    return store.connect()


def _ask_dict(row) -> dict:
    return {
        "ts": row[0], "question": row[1], "answer": row[2],
        "kind": row[3] or "text", "image_path": row[4] or "", "id": row[5],
        "conversation_id": row[6] if len(row) > 6 else None,
    }


@router.get("/api/config")
def get_config(_=Depends(require_token)):
    return load_config().public()


@router.get("/api/today")
def today(_=Depends(require_token)):
    conn = _conn()
    try:
        day = datetime.date.today().isoformat()
        focus = store.focus_stats(conn, day=day)
        asks = store.recent_asks(conn, limit=10, day=day, with_conversation=True)
        ask_count = int(conn.execute(
            "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (f"{day}%",)).fetchone()[0] or 0)
        transcript_count, chars = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts "
            "WHERE ts_start LIKE ?", (f"{day}%",)).fetchone()
        due = store.due_starred(conn, datetime.date.today())
        cet6 = []
        try:
            cet6 = conn.execute(
                "SELECT paper_title, section, item, COUNT(*), MAX(ts), MAX(paper_id) "
                "FROM cet6_events WHERE ts LIKE ? GROUP BY paper_title, section, item "
                "ORDER BY MAX(ts) DESC LIMIT 10", (f"{day}%",)).fetchall()
        except Exception:
            pass
        return {
            "date": day,
            "focus": {
                "minutes": float(focus.get("分钟") or 0),
                "switches": int(focus.get("切换") or 0),
                "apps": [[name, round(float(mins), 1)] for name, mins in (focus.get("程序") or [])],
            },
            "asks": [_ask_dict(row) for row in asks],
            "ask_count": ask_count,
            "transcripts": {"count": int(transcript_count or 0), "chars": int(chars or 0)},
            "due_reviews": len(due),
            "cet6": [
                {"paper": row[0] or "", "section": row[1] or "", "item": row[2] or "",
                 "count": int(row[3] or 0), "last": row[4] or "",
                 "paper_id": row[5] or row[0] or ""}
                for row in cet6
            ],
        }
    finally:
        conn.close()


@router.get("/api/search")
def search(q: str = "", limit: int = 20, _=Depends(require_token)):
    if not q.strip():
        return {"query": q, "results": []}
    conn = _conn()
    try:
        return {"query": q, "results": core_db.search(conn, q, limit=limit)}
    finally:
        conn.close()


@router.get("/api/wrongbook")
def wrongbook(_=Depends(require_token)):
    conn = _conn()
    try:
        rows = store.starred_asks(conn)
        return {"items": [_ask_dict(row) for row in rows]}
    finally:
        conn.close()


@router.post("/api/wrongbook/{ask_id}/toggle")
def toggle_wrongbook(ask_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        state = store.toggle_star(conn, ask_id)
        return {"id": ask_id, "starred": bool(state)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"改错题本失败：{exc}") from exc
    finally:
        conn.close()


@router.get("/api/cet6/context")
def cet6_context(limit: int = 20, _=Depends(require_token)):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ts, paper_title, section, item, sentence, tags, note, loops, plays "
            "FROM cet6_events ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return {"events": [
            {"ts": row[0], "paper": row[1] or "", "section": row[2] or "",
             "item": row[3] or "", "sentence": row[4], "tags": row[5] or "",
             "note": row[6] or "", "loops": int(row[7] or 0),
             "plays": int(row[8] or 0)}
            for row in rows
        ]}
    finally:
        conn.close()


@router.get("/api/cet6/summary")
def cet6_summary(_=Depends(require_token)):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT paper_title, COUNT(*), COUNT(DISTINCT section), MAX(ts) "
            "FROM cet6_events GROUP BY paper_title ORDER BY MAX(ts) DESC").fetchall()
        return {"papers": [
            {"paper": row[0] or "", "breakpoints": int(row[1] or 0),
             "sections": int(row[2] or 0), "last": row[3] or ""}
            for row in rows
        ]}
    finally:
        conn.close()
