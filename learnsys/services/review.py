"""复习调度编排：读旧状态 → FSRS 计算 → 写 `review_state` 与 `review_log`。

业务规则只有一处：这里。路由只做参数与错误转换。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store
from learnsys.services import fsrs

ITEM_TYPES = store.REVIEW_ITEM_TYPES

# 英语复习的两个 tab：句子卡来自写作/翻译批改，词卡来自生词本。
# 来源白名单是业务口径，只在这里定义；store 只负责按传进来的条件查。
KINDS = {
    "sentence": {"item_types": ("wrong", "accum"),
                 "sources": ("writing", "translation", "sentence"),
                 "accum_kinds": ("writing",), "quota_types": ("wrong",)},
    "word": {"item_types": ("vocab", "accum"), "sources": (),
             "accum_kinds": ("translation",), "quota_types": ("vocab",)},
}
NEW_PER_DAY = 10   # 每个 tab 每天最多进 10 张新卡


def _kind_spec(kind: str) -> dict:
    return KINDS.get(str(kind or "").strip(), {})


def _introduced_today(conn, item_types: tuple, day: str,
                      sources: tuple = ()) -> int:
    """今天已经正式复习过的新卡数（review_log 里 state_before='new'）。

    `sources` 与到期队列同口径：只算本 tab 白名单来源的错题，避免在错题本
    复习 manual/quiz 卡把英语句子 tab 的新卡配额吃光。
    """
    types = tuple(t for t in item_types if t in ITEM_TYPES)
    if not types:
        return 0
    placeholders = ",".join("?" * len(types))
    where = ["substr(ts, 1, 10) = ?", "state_before = 'new'",
             f"item_type IN ({placeholders})"]
    args: list = [str(day)[:10], *types]
    src = tuple(s for s in sources if s)
    if src and "wrong" in types:
        marks = ",".join("?" * len(src))
        where.append("(item_type <> 'wrong' OR item_id IN "
                     f"(SELECT id FROM wrong_items WHERE source IN ({marks})))")
        args.extend(src)
    row = conn.execute(
        "SELECT count(*) FROM review_log WHERE " + " AND ".join(where),
        args).fetchone()
    return int(row[0] or 0)


def _exists(conn, item_type: str, item_id: int) -> bool:
    if item_type == "wrong":
        return store.get_wrong_item(conn, item_id) is not None
    if item_type == "vocab":
        return store.get_vocab(conn, item_id) is not None
    if item_type == "accum":
        return store.accum_item(conn, item_id) is not None
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


def review_wrong_item(conn, item_id: int, result: str) -> dict | None:
    """兼容旧调用：remember → FSRS 评分 3，forgot → 评分 1。"""
    rating = 1 if str(result or "").strip().lower() == "forgot" else 3
    try:
        review(conn, "wrong", int(item_id), rating)
    except LookupError:
        return None
    return store.get_wrong_item(conn, int(item_id))


def bump_review_stage(conn, item_ids: list[int]) -> None:
    """兼容旧名字：按「记得」推进一次 FSRS。"""
    for item_id in item_ids or []:
        review_wrong_item(conn, int(item_id), "remember")


def queue(conn, *, limit: int = 50, item_type: str = "",
          kind: str = "", today=None) -> dict:
    store.seed_review_states(conn)
    day = str(today or dt.date.today().isoformat())[:10]
    spec = _kind_spec(kind)
    if spec:
        # 每日积累是当天的固定 10 张，不占旧错题/生词的 10 张新卡配额。
        introduced = _introduced_today(
            conn, spec.get("quota_types", spec["item_types"]), day,
            sources=spec.get("sources", ()))
        new_left = max(0, NEW_PER_DAY - introduced)
        items = store.due_review_items(
            conn, limit=limit, today=day,
            item_types=spec["item_types"], sources=spec["sources"],
            accum_kinds=spec.get("accum_kinds", ()), max_new=new_left)
        return {"items": items, "count": len(items), "kind": kind,
                "new_per_day": NEW_PER_DAY, "new_remaining": new_left,
                "quota_types": list(spec.get("quota_types", spec["item_types"]))}
    items = store.due_review_items(conn, limit=limit, item_type=item_type,
                                   today=day)
    return {"items": items, "count": len(items)}


def due_counts(conn, today=None) -> dict:
    """今日页用：只数句子/词各有多少到期，不建队列、不写复习状态。"""
    day = str(today or dt.date.today().isoformat())[:10]
    return {kind: store.due_review_count(
        conn, today=day, item_types=spec["item_types"],
        sources=spec["sources"], accum_kinds=spec.get("accum_kinds", ()))
        for kind, spec in KINDS.items()}


def stats(conn, item_type: str = "", kind: str = "", today=None) -> dict:
    store.seed_review_states(conn)
    spec = _kind_spec(kind)
    if spec:
        return store.review_counts(
            conn, today=today, item_types=spec["item_types"],
            sources=spec["sources"], accum_kinds=spec.get("accum_kinds", ()))
    return store.review_stats(conn, item_type=item_type, today=today)


def recent_log(conn, limit: int = 20) -> dict:
    return {"items": store.recent_review_log(conn, limit=limit)}
