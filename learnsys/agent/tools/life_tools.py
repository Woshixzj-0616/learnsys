"""生活域只读工具：订阅卡片、事务箱。"""
from __future__ import annotations

import datetime as dt

from learnsys import store

from .context import ToolContext, _one_line

STATUS_LABEL = {"open": "未完成", "done": "已完成", "archived": "已归档"}
KIND_LABEL = {"todo": "待办", "habit": "作息记录", "note": "备注"}


def _due_text(due: str) -> str:
    if not due:
        return "不限期"
    today = dt.date.today().isoformat()
    if due < today:
        try:
            days = (dt.date.fromisoformat(today)
                    - dt.date.fromisoformat(due)).days
        except ValueError:
            days = 0
        return f"到期 {due}（逾期 {days} 天）"
    if due == today:
        return f"到期 {due}（今天）"
    return f"到期 {due}"


def life_items(status: str = "open", limit: int = 10, *,
               ctx: ToolContext) -> str:
    """读生活事务箱；只读，不改状态。"""
    status = str(status or "open")
    if status != "all" and status not in store.LIFE_ITEM_STATUSES:
        status = "open"
    limit = max(1, min(int(limit or 10), 50))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        items = store.list_life_items(conn, status=status, limit=limit)
    except Exception as exc:  # noqa: BLE001 —— 工具失败要如实告诉模型
        return f"读生活事务失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not items:
        return f"生活事务箱里没有{STATUS_LABEL.get(status, '记录')}。"
    lines = [f"生活事务（{STATUS_LABEL.get(status, '全部')}，共 {len(items)} 条）："]
    for item in items:
        kind = KIND_LABEL.get(item.get("kind") or "", item.get("kind") or "")
        parts = [f"- [{kind}] {item.get('title') or ''}",
                 _due_text(str(item.get("due_date") or ""))]
        if item.get("value"):
            parts.append(str(item["value"]))
        note = _one_line(item.get("note") or "", 80)
        if note:
            parts.append(f"备注：{note}")
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def life_cards(days: int = 1, limit: int = 10, *,
               ctx: ToolContext) -> str:
    """读最近 N 天的生活订阅卡片；没有就直说，不编造内容。"""
    days = max(1, min(int(days or 1), 30))
    limit = max(1, min(int(limit or 10), 50))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        items = store.list_recent_cards(conn, days=days, limit=limit)
    except Exception as exc:  # noqa: BLE001 —— 工具失败要如实告诉模型
        return f"读生活卡片失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not items:
        return f"最近 {days} 天没有生活卡片。"
    lines = [f"最近 {days} 天生活卡片（共 {len(items)} 张）："]
    for card in items:
        content = card.get("content") or {}
        summary = _one_line(content.get("summary") or "", 80)
        count = len(content.get("items") or [])
        extra = f"，{count} 条" if count else ""
        read = "已读" if card.get("read") else "未读"
        lines.append(f"- {card['day']} · {card['title']}（{read}{extra}）：{summary}")
    return "\n".join(lines)
