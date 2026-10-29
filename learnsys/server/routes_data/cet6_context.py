"""六级上下文：旧 events 形状 + 新逐句进度 / 最近分析。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from learnsys import store
from learnsys.server.security import require_token
from .common import _conn

router = APIRouter()


@router.get("/api/cet6/context")
def cet6_context(paper_id: str = "", section: str = "", item: str = "",
                 limit: int = 20, _=Depends(require_token)):
    """六级上下文：旧前端只读 `events`；新前端按段读 `sentences` + 最近分析。"""
    conn = _conn()
    try:
        events = store.cet6_recent_events(conn, limit=max(1, min(limit, 100)))
        out = {"events": [
            {"ts": row["ts"], "paper": row["paper"], "section": row["section"],
             "item": row["item"], "sentence": row["sentence"],
             "tags": "、".join(row["tags"]), "note": row["note"],
             "loops": row["loops"], "plays": row["plays"]}
            for row in events
        ]}
        if not paper_id and not (section and item):
            return out
        from learnsys.services import analysis, results
        if not paper_id:
            latest = store.latest_progress_item(conn)
            if not latest:
                return out
            paper_id, paper = latest["paper_id"], latest["paper"]
            section, item = latest["section"], latest["item"]
        else:
            paper = store.progress_paper_title(conn, paper_id)
        sentences = store.cet6_progress_item(
            conn, paper_id=paper_id, section=section, item=item)
        target = analysis.target_id(paper_id, section, item, "item")
        latest_row = results.latest(
            conn, kind=analysis.ANALYSIS_KIND, target_type="item",
            target_id=target, scope="item")
        out.update({
            "paper_id": paper_id, "paper": paper, "section": section, "item": item,
            "sentences": sentences,
            "latest_analysis": results.to_public(latest_row) if latest_row else None,
            "recent_events": events[:5],
        })
        return out
    finally:
        conn.close()


@router.get("/api/cet6/summary")
def cet6_summary(_=Depends(require_token)):
    conn = _conn()
    try:
        return {"papers": store.cet6_summary(conn)}
    finally:
        conn.close()
