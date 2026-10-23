"""六级整卷审计接口：服务端状态读取 + 写前比对/写入/写后校验。

这两个接口和现有 `/api/cet6/sync`、`/api/cet6/import` 一样不要求令牌，
`file://` 的 `null` Origin 也能访问（见 `security.py::origin_allowed`）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from learnsys import store
from learnsys.server.cet6_models import Cet6PaperSync
from learnsys.services import cet6_sync

router = APIRouter()


@router.get("/api/cet6/state")
def cet6_state(paper_id: str = ""):
    """按试卷返回服务端进度，供新浏览器/清缓存后恢复本地状态。"""
    paper_id = (paper_id or "").strip()
    if not paper_id:
        raise HTTPException(status_code=400, detail="缺少 paper_id")
    conn = store.connect()
    try:
        rows = store.cet6_progress_paper_rows(conn, paper_id)
    finally:
        conn.close()
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["section"], row["item"])
        bucket = grouped.get(key)
        if bucket is None:
            bucket = grouped[key] = {"section": row["section"], "item": row["item"],
                                     "sentences": []}
        bucket["sentences"].append({
            "sentence": row["sentence"], "en": row["en"], "tags": row["tags"],
            "note": row["note"], "loops": row["loops"], "plays": row["plays"],
            "done": row["done"],
        })
    return {
        "ok": True,
        "paper_id": paper_id,
        "paper_title": rows[0]["paper_title"] if rows else "",
        "count": len(rows),
        "items": list(grouped.values()),
        "generated_at": store.now(),
    }


@router.post("/api/cet6/sync-paper")
def cet6_sync_paper(req: Cet6PaperSync):
    """整卷审计：写前比对 → 写入 → 写后校验；结果落 cet6_dualwrite_runs。"""
    paper_id = (req.paper_id or "").strip()
    if not paper_id:
        raise HTTPException(status_code=400, detail="缺少 paper_id")
    conn = store.connect()
    try:
        result = cet6_sync.audit_and_write(
            conn,
            paper_id=paper_id,
            paper_title=req.paper,
            items=[item.model_dump() for item in req.items],
            hydration=req.hydration,
            mode=req.mode,
            paper_sig=req.paper_sig,
            client_ts=req.client_ts,
            client_day=req.client_day,
            push_failed=req.push_failed,
            skipped_items=[item.model_dump() for item in req.skipped_items],
        )
    finally:
        conn.close()
    if result.get("status") == "blocked_empty":
        raise HTTPException(status_code=409, detail=result)
    return result
