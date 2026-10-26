"""六级训练今日计划：到期错误卡 → 今天没练的科目 → 下一道题。

今日页行动卡与训练页共用这一个口径，不在前端各自判断「今天练什么」。
- 到期错误卡优先（FSRS 排期，写作/翻译共用错题本）；
- 两科当天都没练时，先写作（成篇输出），再一句一译；
- 连续天数按 `events(module='train')` 算，和 XP 同一来源。
"""
from __future__ import annotations

import datetime

from learnsys import store
from learnsys.services import train_submissions as service

TRAIN_SOURCES = ("writing", "translation")
KIND_LABEL = {"writing": "写作", "translation": "翻译"}


def due_cards(conn, today=None) -> list[dict]:
    """写作/翻译来源的到期错误卡（错题本里同一张表）。"""
    rows = store.wrong_due_items(conn, today)
    return [row for row in rows if row.get("source") in TRAIN_SOURCES]


def _streak(days: set[str]) -> int:
    cursor = datetime.date.today()
    if cursor.isoformat() not in days:
        cursor -= datetime.timedelta(days=1)
    count = 0
    while cursor.isoformat() in days:
        count += 1
        cursor -= datetime.timedelta(days=1)
    return count


def today_activity(conn, day: str) -> dict:
    counts = store.activity_counts(conn, day)
    counts["total"] = (counts["writing"] + counts["translation"]
                       + counts["sentence"])
    return counts


def _next_prompt(conn, kind: str) -> dict | None:
    """没练过的第一题；全练过就挑最近档位最低的。"""
    items = service.list_prompts(conn, kind).get("items") or []
    fresh = next((item for item in items if not item.get("done")), None)
    if fresh:
        return fresh
    rated = [item for item in items if item.get("last_band") is not None]
    return min(rated, key=lambda item: item["last_band"]) if rated else (
        items[0] if items else None)


def _writing_task(conn) -> dict:
    item = _next_prompt(conn, "writing") or {}
    target = item.get("target_words") or [150, 200]
    detail = (f"{item.get('type') or '练习'} · {item.get('minutes') or 30} 分钟 · "
              f"目标 {target[0]}–{target[1]} 词")
    return {
        "kind": "writing", "mode": "practice",
        "prompt_id": item.get("id", ""),
        "title": item.get("title") or "写作练习",
        "detail": detail,
        "href": "#/cet6?tab=writing",
        "label": "开始写作",
    }


def _translation_task(conn) -> dict:
    item = _next_prompt(conn, "translation") or {}
    return {
        "kind": "translation", "mode": "sentence",
        "prompt_id": item.get("id", ""),
        "title": "一句一译",
        "detail": "先写一句英文，提交后立即审核；约 2 秒",
        "href": "#/cet6?tab=translation",
        "label": "开始翻译",
    }


def _task(conn, due: list[dict], today: dict) -> dict | None:
    if due:
        writing = sum(1 for row in due if row.get("source") == "writing")
        translation = len(due) - writing
        return {
            "kind": "review", "mode": "review", "prompt_id": "",
            "title": f"复习 {len(due)} 张到期错误卡",
            "detail": f"写作 {writing} 张 · 翻译 {translation} 张",
            "href": "#/wrongbook",
            "label": "去复习",
        }
    if not today["writing"]:
        return _writing_task(conn)
    if not today["translation"] and not today["sentence"]:
        return _translation_task(conn)
    return None


def plan(conn, day: str = "", due: list | None = None) -> dict:
    """`due` 可传入今日页已经查好的到期列表，避免同一请求里重复扫错题本。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    if due is None:
        due = due_cards(conn, day)
    else:
        due = [row for row in due if row.get("source") in TRAIN_SOURCES]
    today = today_activity(conn, day)
    return {
        "date": day,
        "streak": _streak(store.event_days(conn, "train")),
        "today": today,
        "due": {
            "total": len(due),
            "writing": sum(1 for row in due if row.get("source") == "writing"),
            "translation": sum(1 for row in due if row.get("source") == "translation"),
            "items": [
                {"id": row.get("id"), "source": row.get("source"),
                 "question": row.get("question", ""), "tags": row.get("tags", ""),
                 "next_review": row.get("next_review", "")}
                for row in due[:20]
            ],
        },
        "task": _task(conn, due, today),
    }


def list_errors(conn, kind: str = "", status: str = "all",
                limit: int = 200) -> dict:
    """写作/翻译错误卡；不传 kind 就合并两类。"""
    sources = (kind,) if kind in TRAIN_SOURCES else TRAIN_SOURCES
    items: list[dict] = []
    for source in sources:
        items.extend(store.wrong_items(conn, source=source, status=status,
                                       limit=limit))
    items.sort(key=lambda row: (str(row.get("next_review") or ""),
                                str(row.get("ts") or "")))
    items = items[:max(1, min(int(limit or 200), 500))]
    return {
        "items": items,
        "count": len(items),
        "by_source": {
            source: sum(1 for row in items if row.get("source") == source)
            for source in sources
        },
    }
