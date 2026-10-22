"""资料库工具：检索、读正文、保存笔记。"""
from __future__ import annotations

import hashlib

from learnsys import store
from .context import ToolContext


def search_materials(query: str, limit: int = 5, *, ctx: ToolContext) -> str:
    """搜资料库，返回带资料 id / 页码 / 命中段的文本。"""
    from learnsys.materials import search as material_search
    query = str(query or "").strip()
    if not query:
        return "搜索词是空的。"
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        hits = material_search.search(conn, query, limit=max(1, min(int(limit or 5), 10)))
    except Exception as exc:
        return f"搜资料库失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not hits:
        return f"资料库里没有和「{query}」相关的内容。"
    lines = [f"资料库里找到 {len(hits)} 段和「{query}」相关的内容："]
    for hit in hits:
        page = f" · 第 {hit['page']} 页" if hit.get("page") else ""
        lines.append(f"\n【资料 {hit['material_id']}：{hit['title']}{page}】\n{hit['snippet']}")
    return "\n".join(lines)


def read_material(material_id: int, offset: int = 0, length: int = 6000,
                  *, ctx: ToolContext) -> str:
    """按 id 分段读资料正文。"""
    offset = max(0, int(offset or 0))
    length = max(500, min(int(length or 6000), 20000))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        item = store.get_material(conn, material_id)
        if item is None:
            return f"没有 id={material_id} 这份资料。"
        store.touch_material(conn, material_id)
    except Exception as exc:
        return f"读资料失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    body = str(item.get("body") or "")
    piece = body[offset:offset + length]
    page_info = ""
    if "\f" in body:
        start_page = body[:offset].count("\f") + 1
        end_page = body[:offset + len(piece)].count("\f") + 1
        page_info = (f"第 {start_page} 页" if start_page == end_page
                     else f"第 {start_page}–{end_page} 页") + "；"
    head = (f"【{item['title']}】共 {len(body)} 字；{page_info}"
            f"本次读 {offset}–{offset + len(piece)} 字")
    tail = "" if offset + len(piece) >= len(body) else (
        f"\n（后面还有 {len(body) - offset - len(piece)} 字，offset="
        f"{offset + len(piece)} 接着读）")
    return head + "\n" + piece + tail


def save_material_note(title: str, content: str, tags: str = "",
                       *, ctx: ToolContext) -> str:
    """把笔记存进资料库（materials 表）；同内容只留一份。"""
    title = " ".join(str(title or "").split())[:120] or "未命名笔记"
    body = str(content or "")
    if not body.strip():
        return "笔记内容是空的，没有保存。"
    if len(body) > 200_000:
        return "笔记太长（上限 20 万字），没有保存。请压缩或分成几份。"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        item_id, created = store.add_material(
            conn, title=title, kind="note", source="agent", body=body,
            tags=str(tags or ""), sha256=digest)
    except Exception as exc:
        return f"资料库保存失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if created:
        return (f"已保存进资料库（资料 #{item_id}：{title}，{len(body)} 字）。"
                "用户可以在「资料」页看到、检索和挂到问一问。")
    return f"资料库里已经存在这份内容（资料 #{item_id}），没有重复保存。"
