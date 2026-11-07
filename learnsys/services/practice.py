"""实践经验库：校验与状态规则唯一落点。

只强制三格：场景 / 坑或有效点 / 下次。技术原因与证据可选，通常由 AI 起草。
"""
from __future__ import annotations

from learnsys import store

KINDS = ("pitfall", "good_practice")
TITLE_MAX = 120
FIELD_MAX = 4000
TAGS_MAX = 200


def _text(value, max_len: int) -> str:
    return str(value or "").strip()[:max_len]


def _kind(value) -> str:
    kind = str(value or "").strip()
    return kind if kind in KINDS else "pitfall"


def create(conn, payload: dict) -> dict:
    title = _text(payload.get("title"), TITLE_MAX)
    scene = _text(payload.get("scene"), FIELD_MAX)
    pitfall = _text(payload.get("pitfall"), FIELD_MAX)
    next_time = _text(payload.get("next_time"), FIELD_MAX)
    if not title:
        raise ValueError("标题不能为空")
    if not scene or not pitfall or not next_time:
        raise ValueError("场景、坑 / 有效点、下次三格都要填")
    return store.add_note(
        conn, title=title, scene=scene, pitfall=pitfall, next_time=next_time,
        kind=_kind(payload.get("kind")),
        why=_text(payload.get("why"), FIELD_MAX),
        evidence=_text(payload.get("evidence"), FIELD_MAX),
        tags=_text(payload.get("tags"), TAGS_MAX),
        project_id=int(payload.get("project_id") or 0),
        source=_text(payload.get("source"), 40) or "manual",
        source_id=_text(payload.get("source_id"), 120))


def update(conn, note_id: int, payload: dict) -> dict | None:
    fields: dict = {}
    if "title" in payload:
        title = _text(payload.get("title"), TITLE_MAX)
        if not title:
            raise ValueError("标题不能为空")
        fields["title"] = title
    for key in ("scene", "pitfall", "next_time"):
        if key in payload:
            value = _text(payload.get(key), FIELD_MAX)
            if not value:
                raise ValueError("场景、坑 / 有效点、下次三格都要填")
            fields[key] = value
    if "kind" in payload:
        fields["kind"] = _kind(payload.get("kind"))
    for key in ("why", "evidence"):
        if key in payload:
            fields[key] = _text(payload.get(key), FIELD_MAX)
    if "tags" in payload:
        fields["tags"] = _text(payload.get("tags"), TAGS_MAX)
    if "project_id" in payload:
        fields["project_id"] = int(payload.get("project_id") or 0)
    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        fields["status"] = status if status in ("active", "archived") else "active"
    return store.update_note(conn, note_id, **fields)


def get(conn, note_id: int) -> dict | None:
    return store.get_note(conn, note_id)


def list_notes(conn, *, query: str = "", tag: str = "", project_id: int = 0,
               status: str = "active", limit: int = 200) -> dict:
    items = store.list_notes(
        conn, query=query, tag=tag, project_id=project_id,
        status=status or "active", limit=limit)
    return {"items": items, "count": len(items)}


def used(conn, note_id: int) -> dict | None:
    return store.use_note(conn, note_id)


def archive(conn, note_id: int) -> dict | None:
    return store.archive_note(conn, note_id)


def delete(conn, note_id: int) -> bool:
    return store.delete_note(conn, note_id)
