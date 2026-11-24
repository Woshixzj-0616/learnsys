"""问答反馈：答对 / 答偏 / 资料不对，挂到一次 agent_run 上。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token

router = APIRouter()


class FeedbackRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)
    verdict: str = Field(min_length=2, max_length=16)
    note: str = Field(default="", max_length=500)


@router.post("/api/agent/qa_feedback")
def qa_feedback(req: FeedbackRequest, _=Depends(require_token)):
    if req.verdict not in store.QA_FEEDBACK_VERDICTS:
        raise HTTPException(status_code=400, detail="未知反馈类型")
    conn = store.connect()
    try:
        if store.get_agent_run(conn, run_id=req.run_id) is None:
            raise HTTPException(status_code=404, detail="这条运行记录不存在")
        feedback_id = store.add_qa_feedback(
            conn, req.run_id, req.verdict, note=req.note)
    finally:
        conn.close()
    return {"ok": True, "id": feedback_id}
