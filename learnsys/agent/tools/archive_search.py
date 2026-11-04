"""只读检索：在封存的对话总汇里找原文片段。"""
from __future__ import annotations

from learnsys.services.dialog_archive import search

from .context import ToolContext


def search_dialog_archive(query: str, limit: int = 8, *,
                          ctx: ToolContext) -> str:
    path = search.latest_archive(ctx.data_root)
    if path is None:
        return "还没有封存的对话总汇；先运行 tools/build_dialog_archive.py。"
    hits = search.search_archive(path, query, limit=limit)
    if not hits:
        return f"对话总汇里没有找到「{query}」。"
    lines = []
    for item in hits:
        date = (item.get("at") or "")[:10] or "日期未知"
        lines.append(
            f"- {date} · {item.get('role')} · {item['anchor']}\n"
            f"  {item['snippet']}")
    return "\n".join(lines)
