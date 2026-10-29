"""个人 AI 工作台接口：首页三域 + 偏好 / 项目 / 订阅。

只做鉴权、参数校验与返回；数据装配在 `services/home.py`，SQL 在 `store/personal.py`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import home as home_service
from .common import _conn

router = APIRouter()


class FactBody(BaseModel):
    id: int = 0
    kind: str = "preference"
    content: str = ""
    evidence: str = ""
    confidence: float = 0.5
    status: str = "active"


class ProjectBody(BaseModel):
    name: str = ""
    repo_path: str = ""
    handoff_path: str = ""
    status: str = "active"
    next_step: str = ""
    risk: str = ""


class SubscriptionBody(BaseModel):
    topic: str = ""
    kind: str = "news"
    cadence: str = "daily"
    at_time: str = "07:30"
    sources: list[str] = Field(default_factory=list)
    enabled: bool = True


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _valid_time(value: str) -> bool:
    try:
        hour, minute = (int(part) for part in str(value).split(":", 1))
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


@router.get("/api/home")
def home(day: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        return home_service.payload(conn, day)
    finally:
        conn.close()


# ----------------------------------------------------------------- profile facts

@router.get("/api/profile/facts")
def list_facts(kind: str = "", status: str = "active",
               _=Depends(require_token)):
    conn = _conn()
    try:
        items = store.list_facts(conn, kind=kind, status=status)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/profile/facts")
def save_fact(body: FactBody, _=Depends(require_token)):
    if body.kind not in store.PERSONAL_FACT_KINDS:
        raise _bad("偏好类型只能是 preference / goal / constraint")
    if body.status not in store.PERSONAL_FACT_STATUSES:
        raise _bad("状态只能是 active / archived")
    if not body.content.strip():
        raise _bad("偏好内容不能为空")
    conn = _conn()
    try:
        if body.id and store.get_fact(conn, body.id) is None:
            raise HTTPException(status_code=404, detail="没有找到这条偏好")
        try:
            item = store.upsert_fact(
                conn, fact_id=body.id, kind=body.kind, content=body.content,
                evidence=body.evidence, confidence=body.confidence,
                status=body.status)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条偏好")
        return item
    finally:
        conn.close()


@router.post("/api/profile/facts/{fact_id}/archive")
def archive_fact(fact_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.archive_fact(conn, fact_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条偏好")
        return item
    finally:
        conn.close()


# --------------------------------------------------------------------- projects

@router.get("/api/projects")
def list_projects(status: str = "", _=Depends(require_token)):
    conn = _conn()
    try:
        items = store.list_projects(conn, status=status)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/projects")
def save_project(body: ProjectBody, _=Depends(require_token)):
    if body.status not in store.PERSONAL_PROJECT_STATUSES:
        raise _bad("项目状态只能是 active / paused / archived")
    if not body.name.strip():
        raise _bad("项目名不能为空")
    conn = _conn()
    try:
        try:
            return store.upsert_project(
                conn, name=body.name, repo_path=body.repo_path,
                handoff_path=body.handoff_path, status=body.status,
                next_step=body.next_step, risk=body.risk)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------- subscriptions

@router.get("/api/subscriptions")
def list_subscriptions(enabled_only: bool = False, _=Depends(require_token)):
    conn = _conn()
    try:
        items = store.list_subscriptions(conn, enabled_only=enabled_only)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/subscriptions")
def save_subscription(body: SubscriptionBody, _=Depends(require_token)):
    if body.kind not in store.PERSONAL_SUBSCRIPTION_KINDS:
        raise _bad("订阅类型只能是 news / word / price / stock / custom")
    if body.cadence not in store.PERSONAL_CADENCES:
        raise _bad("频率只能是 daily / weekly")
    if not _valid_time(body.at_time):
        raise _bad("提醒时间要用 HH:MM 格式")
    if not body.topic.strip():
        raise _bad("订阅主题不能为空")
    conn = _conn()
    try:
        try:
            return store.upsert_subscription(
                conn, topic=body.topic, kind=body.kind, cadence=body.cadence,
                at_time=body.at_time, sources=body.sources,
                enabled=body.enabled)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/subscriptions/{sub_id}/run")
def run_subscription(sub_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.mark_run(conn, sub_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条订阅")
        return item
    finally:
        conn.close()
