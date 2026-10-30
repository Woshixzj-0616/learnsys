"""生活域只读工具：订阅卡片。"""
from __future__ import annotations

from learnsys import store

from .context import ToolContext, _one_line


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
