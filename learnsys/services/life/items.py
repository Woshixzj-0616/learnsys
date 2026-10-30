"""生活事务箱：到期提醒与状态机。

存储与 SQL 在 `store/life_items.py`；这里只做判定：
- 到期日格式；
- open → done → archived 的合法转换；
- 首页/Agent 用的提醒文案（顺序由调用方决定）。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store

TRANSITIONS = {
    "open": {"done", "archived"},
    "done": {"open", "archived"},
    "archived": {"open"},
}


def validate(kind: str, due_date: str) -> None:
    """类型与到期日校验；失败抛中文 ValueError。"""
    if str(kind or "todo") not in store.LIFE_ITEM_KINDS:
        raise ValueError("事务类型只能是 todo / habit / note")
    value = str(due_date or "").strip()
    if not value:
        return
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("到期日要用 YYYY-MM-DD 格式") from exc


def summary(conn, day: str) -> dict:
    day = str(day)[:10]
    items = store.due_life_items(conn, day)
    counts = store.life_item_counts(conn, day)
    return {
        "items": items,
        "due_count": len(items),
        "item_count": counts["open"],
        "overdue_count": counts["overdue"],
    }


def reminder_lines(conn, day: str, *, limit: int = 2) -> list[str]:
    day = str(day)[:10]
    lines: list[str] = []
    for item in store.due_life_items(conn, day, limit=limit):
        due = str(item.get("due_date") or "")
        if due and due < day:
            try:
                days = (dt.date.fromisoformat(day)
                        - dt.date.fromisoformat(due)).days
            except ValueError:
                days = 0
            suffix = f"（逾期 {days} 天）" if days else "（今天）"
        else:
            suffix = "（今天）"
        lines.append(f"待办：{item.get('title') or ''}{suffix}")
    return lines


def change_status(conn, item_id: int, target: str) -> dict | None:
    target = str(target or "")
    if target not in store.LIFE_ITEM_STATUSES:
        raise ValueError("事务状态只能是 open / done / archived")
    item = store.get_life_item(conn, item_id)
    if item is None:
        return None
    if item["status"] == target:
        return item
    if target not in TRANSITIONS.get(item["status"], set()):
        raise ValueError(f"不能把「{item['status']}」直接改成「{target}」")
    return store.set_life_item_status(conn, item_id, target)
