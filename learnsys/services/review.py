"""复习调度编排：读旧状态 → FSRS 计算 → 写 `review_state` 与 `review_log`。

业务规则只有一处：这里。路由只做参数与错误转换。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store
from learnsys.services import fsrs

ITEM_TYPES = store.REVIEW_ITEM_TYPES


def _exists(conn, item_type: str, item_id: int) -> bool:
    if item_type == "wrong":
        return store.get_wrong_item(conn, item_id) is not None
    if item_type == "vocab":
        return store.get_vocab(conn, item_id) is not None
    return False


def _new_state() -> dict:
    return {
        "state": "new", "due": dt.date.today().isoformat(), "stability": 0.0,
        "difficulty": 0.0, "reps": 0, "lapses": 0, "last_review": "",
        "scheduled_days": 0, "elapsed_days": 0,
    }


def review(conn, item_type: str, item_id: int, rating: int,
           now: dt.datetime | None = None) -> dict:
    """提交一次复习；返回新状态与下次到期日。"""
    if item_type not in ITEM_TYPES:
        raise ValueError("不支持的卡片类型：" + str(item_type))
    if rating not in (1, 2, 3, 4):
        raise ValueError("评分必须是 1–4")
    if not _exists(conn, item_type, int(item_id)):
        raise LookupError("卡片不存在")
    store.seed_review_states(conn)
    old = store.get_review_state(conn, item_type, int(item_id)) or _new_state()
    new = fsrs.schedule(old, int(rating), now)
    store.save_review_state(conn, item_type, int(item_id), **new)
    store.add_review_log(
        conn, item_type=item_type, item_id=int(item_id), rating=int(rating),
        state_before=old.get("state") or "new", due_before=old.get("due") or "",
        due_after=new["due"], stability=new["stability"],
        difficulty=new["difficulty"], elapsed_days=new["elapsed_days"],
        scheduled_days=new["scheduled_days"])
    return {
        "state": new,
        "next_review": new["due"],
        "rating": int(rating),
        "rating_name": fsrs.RATING_NAMES[int(rating)],
        "scheduled_days": new["scheduled_days"],
    }


def queue(conn, *, limit: int = 50, item_type: str = "") -> dict:
    store.seed_review_states(conn)
    items = store.due_review_items(conn, limit=limit, item_type=item_type)
    return {"items": items, "count": len(items)}


def stats(conn) -> dict:
    store.seed_review_states(conn)
    return store.review_stats(conn)


def recent_log(conn, limit: int = 20) -> dict:
    return {"items": store.recent_review_log(conn, limit=limit)}
