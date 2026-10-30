"""个人 AI 工作台接口：首页三域 + 偏好 / 项目 / 订阅。

只做鉴权、参数校验与返回；数据装配在 `services/home.py`，SQL 在 `store/personal.py`。
"""
from __future__ import annotations

import pathlib
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import handoff as handoff_service
from learnsys.services import home as home_service
from learnsys.services import life as life_service
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


class ProjectPatch(BaseModel):
    """部分更新；字段缺省/为空表示不改，显式传空串才会清空。"""
    name: str | None = None
    repo_path: str | None = None
    handoff_path: str | None = None
    status: str | None = None
    next_step: str | None = None
    risk: str | None = None


class SubscriptionBody(BaseModel):
    topic: str = ""
    kind: str = "news"
    cadence: str = "daily"
    at_time: str = "07:30"
    sources: list[str] = Field(default_factory=list)
    enabled: bool = True


class SubscriptionPatch(BaseModel):
    topic: str | None = None
    kind: str | None = None
    cadence: str | None = None
    at_time: str | None = None
    sources: list[str] | None = None
    enabled: bool | None = None


class CardReadBody(BaseModel):
    read: bool = True


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
def list_projects(status: str = "active", _=Depends(require_token)):
    """默认只列进行中；`status=all` 看全部（含已归档）。"""
    conn = _conn()
    try:
        items = store.list_projects(conn, status="" if status == "all" else status)
        for item in items:
            raw = str(item.get("repo_path") or "").strip()
            item["repo_exists"] = bool(raw) and pathlib.Path(raw).is_dir()
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


@router.patch("/api/projects/{project_id}")
def patch_project(project_id: int, body: ProjectPatch,
                  _=Depends(require_token)):
    changes = body.model_dump(exclude_none=True)
    if "status" in changes and changes["status"] not in store.PERSONAL_PROJECT_STATUSES:
        raise _bad("项目状态只能是 active / paused / archived")
    conn = _conn()
    try:
        try:
            item = store.update_project(conn, project_id, **changes)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise _bad("项目名已经存在") from exc
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这个项目")
        return item
    finally:
        conn.close()


@router.post("/api/projects/{project_id}/archive")
def archive_project(project_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.archive_project(conn, project_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这个项目")
        return item
    finally:
        conn.close()


@router.post("/api/projects/{project_id}/handoff")
def generate_handoff(project_id: int, _=Depends(require_token)):
    """生成本地 HANDOFF；只写数据目录，不写回项目仓库。"""
    conn = _conn()
    try:
        project = store.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="没有找到这个项目")
        text, path = handoff_service.write(conn, project)
        return {"path": str(path), "text": text,
                "project": store.get_project(conn, project_id)}
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/handoff")
def read_handoff(project_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        project = store.get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="没有找到这个项目")
        path = handoff_service.output_path(project)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="还没有生成交接页")
        return {"path": str(path),
                "text": path.read_text(encoding="utf-8")}
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


@router.patch("/api/subscriptions/{sub_id}")
def update_subscription(sub_id: int, body: SubscriptionPatch,
                        _=Depends(require_token)):
    if body.kind is not None and body.kind not in store.PERSONAL_SUBSCRIPTION_KINDS:
        raise _bad("订阅类型只能是 news / word / price / stock / custom")
    if body.cadence is not None and body.cadence not in store.PERSONAL_CADENCES:
        raise _bad("频率只能是 daily / weekly")
    if body.at_time is not None and not _valid_time(body.at_time):
        raise _bad("提醒时间要用 HH:MM 格式")
    changes = {key: value for key, value in body.model_dump().items()
               if key != "sources" and value is not None}
    conn = _conn()
    try:
        try:
            item = store.update_subscription(
                conn, sub_id, sources=body.sources, **changes)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise _bad("同类型同主题的订阅已经存在") from exc
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条订阅")
        return item
    finally:
        conn.close()


@router.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.delete_subscription(conn, sub_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条订阅")
        return {"deleted": True, "id": int(sub_id)}
    finally:
        conn.close()


@router.post("/api/subscriptions/{sub_id}/run")
def run_subscription(sub_id: int, _=Depends(require_token)):
    """立即生成一次；成功返回订阅对象（含 `last_run`）和当天卡片。"""
    conn = _conn()
    try:
        item = store.get_subscription(conn, sub_id)
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这条订阅")
        try:
            card = life_service.generate(conn, item)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        updated = store.mark_run(conn, sub_id) or item
        return {**updated, "card": card}
    finally:
        conn.close()


# ---------------------------------------------------------------- life cards

@router.get("/api/life/cards")
def list_life_cards(day: str = "", limit: int = 50, _=Depends(require_token)):
    conn = _conn()
    try:
        if day:
            items = store.list_cards(conn, day=day, domain="life", limit=limit)
        else:
            items = store.list_recent_cards(conn, days=1, limit=limit)
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


@router.post("/api/life/cards/{card_id}/read")
def read_life_card(card_id: int, body: CardReadBody,
                   _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.mark_read(conn, card_id, bool(body.read))
        if item is None:
            raise HTTPException(status_code=404, detail="没有找到这张卡片")
        return item
    finally:
        conn.close()
