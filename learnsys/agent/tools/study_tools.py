"""学习数据工具：错题、长期记忆、六级进度。"""
from __future__ import annotations

import datetime

from learnsys import store
from .context import ToolContext, _one_line, _stamp


def save_wrongbook(question: str, my_answer: str, correct_answer: str = "",
                   tags: str = "", *, ctx: ToolContext) -> str:
    """测验判错时把题收进错题本；同会话同题只收一次。"""
    if ctx.mode != "quiz":
        return "只有测验模式能自动收错题。"
    question = str(question or "").strip()
    my_answer = str(my_answer or "").strip()
    if not question or not my_answer:
        return "缺少题目或我的作答，没有保存。"
    ref = str(ctx.conversation_id or ctx.conversation_key or "0")
    fingerprint = store.wrong_fingerprint(question)
    key = f"{ref}:{fingerprint}"
    if key in ctx.saved:
        return "这道题本轮已经收过了，不用重复收。"
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        item_id, created = store.add_wrong_item(
            conn, question=question, answer=correct_answer, my_answer=my_answer,
            tags=tags, source="quiz", source_id=f"quiz:{ref}:{fingerprint}",
            auto=True, material_id=ctx.material_id)
    except Exception as exc:
        return f"错题本保存失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    ctx.saved.add(key)
    if created:
        return f"已收进错题本（#{item_id}）。"
    return f"这道题已经在错题本里（#{item_id}），没有重复添加。"


def get_cet6_context(paper_id: str = "", section: str = "", item: str = "",
                     limit: int = 40, *, ctx: ToolContext | None = None) -> str:
    """读六级逐句进度 + 最近分析；没记录就直说。"""
    limit = max(1, min(int(limit or 40), 120))
    conn = store.connect(ctx.db_path if ctx and ctx.db_path else None)
    try:
        if not paper_id:
            row = conn.execute(
                "SELECT paper_id, section, item FROM cet6_progress "
                "ORDER BY updated_at DESC LIMIT 1").fetchone()
            if not row:
                return "还没有六级精听记录。"
            paper_id, section, item = row[0], row[1], row[2]
        elif not section or not item:
            row = conn.execute(
                "SELECT section, item FROM cet6_progress WHERE paper_id = ? "
                "ORDER BY updated_at DESC LIMIT 1", (paper_id,)).fetchone()
            if not row:
                return "这份试卷还没有六级精听记录。"
            section = section or row[0]
            item = item or row[1]
        rows = store.cet6_progress_item(
            conn, paper_id=paper_id, section=section, item=item)
        if not rows:
            return "这一段还没有六级精听记录。"
        title_row = conn.execute(
            "SELECT MAX(paper_title) FROM cet6_progress WHERE paper_id = ?",
            (paper_id,)).fetchone()
        paper_title = (title_row[0] if title_row and title_row[0] else paper_id)
        lines = [f"六级精听：{paper_title} / {section} / {item}（共 {len(rows)} 句）"]
        for row in rows[:limit]:
            line = [f"第 {row['sentence']} 句", "已完成" if row["done"] else "未完成"]
            if row["tags"]:
                line.append("标签：" + "、".join(row["tags"]))
            if row["note"]:
                line.append("我的原因：" + row["note"])
            if row["loops"] or row["plays"]:
                line.append(f"循环回绕 {row['loops']} 次 / 共播放 {row['plays']} 次")
            lines.append(" | ".join(line))
            if row["en"]:
                lines.append("  " + row["en"])
        if len(rows) > limit:
            lines.append(f"（只显示前 {limit} 句，共 {len(rows)} 句）")
        from learnsys.services import analysis, results
        target = analysis.target_id(paper_id, section, item, "item")
        latest = results.latest(
            conn, kind=analysis.ANALYSIS_KIND, target_type="item",
            target_id=target, scope="item")
        if latest:
            content = (results.to_public(latest) or {}).get("content") or {}
            summary = str(content.get("summary") or "").strip()
            if summary:
                lines.append("最近一次分析：" + summary[:800])
        return "\n".join(lines)
    finally:
        conn.close()


def save_memory(content: str, kind: str = "preference", *, ctx: ToolContext) -> str:
    """写一条跨会话记忆；同内容不重复记。"""
    text = " ".join(str(content or "").split())
    if len(text) < 2:
        return "记忆内容太短，没有保存。请写成完整的一句话。"
    if len(text) > 500:
        text = text[:500]
    kind = kind if kind in ("preference", "rule", "identity") else "preference"
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        memory_id, created = store.add_memory(conn, text, kind=kind)
    except Exception as exc:
        return f"长期记忆保存失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if created:
        return f"已记住（#{memory_id}）：{text}。以后每轮都会带上；用户说忘掉时用 forget_memory。"
    return f"这条已经在长期记忆里（#{memory_id}）：{text}。"


def forget_memory(memory_id: int, *, ctx: ToolContext) -> str:
    """按编号删除一条长期记忆。"""
    try:
        memory_id = int(memory_id)
    except (TypeError, ValueError):
        return "memory_id 不是整数，没有删除。"
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        deleted = store.delete_memory(conn, memory_id)
    except Exception as exc:
        return f"删除长期记忆失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if deleted:
        return f"已忘掉 #{memory_id}，以后不再生效。"
    return f"没有找到启用中的 #{memory_id}（可能已经删过了）。"


def recent_wrong_items(limit: int = 8, days: int = 0, material_id: int = 0,
                       *, ctx: ToolContext) -> str:
    """读最近的错题；编号就是错题本的 #id，回答可以直接引用。"""
    limit = max(1, min(int(limit or 8), 20))
    days = max(0, min(int(days or 0), 3650))
    material_id = max(0, int(material_id or 0))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        items = store.wrong_items(conn, status="all", limit=500,
                                  material_id=material_id)
    except Exception as exc:
        return f"读错题本失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if days:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        items = [item for item in items if str(item.get("ts") or "")[:10] >= cutoff]
    if not items:
        return "错题本里还没有符合条件的题。"
    lines = [f"最近的错题（新→旧，最多 {limit} 题；编号可直接引用）："]
    for item in items[:limit]:
        material = (f" ｜ 资料：{item['material_title']}"
                    if item.get("material_title") else "")
        tags = f" ｜ 标签：{item['tags']}" if item.get("tags") else ""
        state = "已掌握" if item.get("mastered") else "待复习"
        lines.append(
            f"\n错题 #{item['id']} ｜ {_stamp(item.get('ts'))} ｜ {state}"
            f"{material}{tags}\n"
            f"题目：{_one_line(item.get('question'), 300)}\n"
            f"正确答案：{_one_line(item.get('answer'), 200)}\n"
            f"我的作答：{_one_line(item.get('my_answer'), 200)}")
    lines.append("（以上是错题本原文，不要改写题目；引用时写「错题 #编号」。）")
    return "\n".join(lines)
