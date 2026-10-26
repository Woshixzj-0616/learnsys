"""六级写作/翻译训练接口：题库、草稿、提交、轮询、重批、外部分数。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import train_plan, train_stats
from learnsys.services import train_sentences as sentence_service
from learnsys.services import train_submissions as service

router = APIRouter()


class SubmissionIn(BaseModel):
    kind: str = "writing"
    prompt_id: str = Field(min_length=1, max_length=40)
    mode: str = "practice"
    parent_id: int = 0


class PatchIn(BaseModel):
    text: str | None = Field(default=None, max_length=8000)
    duration_s: int | None = None
    pasted_chars: int | None = None
    left_seconds: int | None = None


class SubmitIn(BaseModel):
    pasted_chars: int = 0
    left_seconds: int = 0


class ScoreIn(BaseModel):
    score: float | None = None


class SentenceReviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    pasted_chars: int = 0
    left_seconds: int = 0


def _call(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _conn():
    return store.connect()


@router.get("/api/cet6/train/prompts")
def train_prompts(kind: str = "writing", _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.list_prompts(conn, kind))
    finally:
        conn.close()


@router.get("/api/cet6/train/prompts/{prompt_id}")
def train_prompt(prompt_id: str, kind: str = "writing",
                 _=Depends(require_token)):
    return _call(lambda: service.prompt_detail(kind, prompt_id))


@router.get("/api/cet6/train/sentences")
def train_sentences(skill: str = "", limit: int = 30, offset: int = 0,
                    _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: sentence_service.list_sentences(
            conn, skill=skill, limit=limit, offset=offset))
    finally:
        conn.close()


@router.get("/api/cet6/train/sentences/{sentence_id}")
def train_sentence(sentence_id: str, _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: sentence_service.get_sentence(conn, sentence_id))
    finally:
        conn.close()


@router.post("/api/cet6/train/sentences/{sentence_id}/review")
def train_sentence_review(sentence_id: str, req: SentenceReviewIn,
                          _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: sentence_service.review_sentence(
            conn, sentence_id, req.text,
            {"pasted_chars": req.pasted_chars,
             "left_seconds": req.left_seconds}))
    finally:
        conn.close()


@router.get("/api/cet6/train/terms")
def train_terms(pack_id: str = "", _=Depends(require_token)):
    return _call(lambda: service.list_terms(pack_id))


@router.get("/api/cet6/train/plan")
def train_plan_view(day: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: train_plan.plan(conn, day))
    finally:
        conn.close()


@router.get("/api/cet6/train/stats")
def train_stats_view(days: int = 30, _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: train_stats.stats(conn, days))
    finally:
        conn.close()


@router.get("/api/cet6/train/errors")
def train_errors(kind: str = "", status: str = "all", limit: int = 200,
                 _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: train_plan.list_errors(
            conn, kind=kind, status=status, limit=limit))
    finally:
        conn.close()


@router.get("/api/cet6/train/submissions")
def train_history(kind: str = "writing", limit: int = 50, offset: int = 0,
                  _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.history(
            conn, kind, limit=limit, offset=offset))
    finally:
        conn.close()


@router.post("/api/cet6/train/submissions", status_code=201)
def train_create(req: SubmissionIn, _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.create_submission(
            conn, kind=req.kind, prompt_id=req.prompt_id,
            mode=req.mode, parent_id=req.parent_id))
    finally:
        conn.close()


@router.patch("/api/cet6/train/submissions/{submission_id}")
def train_patch(submission_id: int, req: PatchIn, _=Depends(require_token)):
    flags = None
    if req.pasted_chars is not None or req.left_seconds is not None:
        flags = {"pasted_chars": req.pasted_chars or 0,
                 "left_seconds": req.left_seconds or 0}
    conn = _conn()
    try:
        return _call(lambda: service.patch_submission(
            conn, submission_id, text=req.text,
            duration_s=req.duration_s, flags=flags))
    finally:
        conn.close()


@router.get("/api/cet6/train/submissions/{submission_id}")
def train_detail(submission_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.detail(conn, submission_id))
    finally:
        conn.close()


@router.post("/api/cet6/train/submissions/{submission_id}/submit")
def train_submit(submission_id: int, req: SubmitIn,
                 _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.submit_submission(
            conn, submission_id, flags=req.model_dump()))
    finally:
        conn.close()


@router.post("/api/cet6/train/submissions/{submission_id}/review")
def train_review(submission_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.review_submission(conn, submission_id))
    finally:
        conn.close()


@router.post("/api/cet6/train/submissions/{submission_id}/external-score")
def train_external_score(submission_id: int, req: ScoreIn,
                         _=Depends(require_token)):
    conn = _conn()
    try:
        return _call(lambda: service.set_external_score(
            conn, submission_id, req.score))
    finally:
        conn.close()
