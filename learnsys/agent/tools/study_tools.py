"""学习数据工具：错题、长期记忆、六级进度。"""
from __future__ import annotations

import datetime

from learnsys import store
from learnsys.services import knowledge, train_plan, train_stats
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


REVIEW_STATE_LABELS = {"new": "新卡", "learning": "学习中",
                       "review": "复习中", "relearning": "重学"}


def due_reviews(limit: int = 20, item_type: str = "",
                *, ctx: ToolContext) -> str:
    """今天到期的错题/生词（FSRS 排期）。"""
    limit = max(1, min(int(limit or 20), 50))
    item_type = item_type if item_type in ("wrong", "vocab") else ""
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        items = store.due_review_items(conn, limit=limit, item_type=item_type)
        stats = store.review_stats(conn, item_type=item_type)
    except Exception as exc:
        return f"读到复习队列失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not items:
        return "今天没有到期的复习。"
    lines = [f"今天到期的复习：{stats['due']} 张"
             f"（今天已复习 {stats['reviewed_today']} 次；最多列出 {limit} 张）"]
    for item in items:
        state = REVIEW_STATE_LABELS.get(item.get("state") or "", item.get("state") or "")
        if item.get("item_type") == "wrong":
            label = f"错题 #{item.get('item_id')}"
            body = _one_line(item.get("question"), 120)
        else:
            label = f"生词「{item.get('word') or ''}」"
            body = _one_line(item.get("meaning"), 120)
        lines.append(
            f"- {label}（{state}，复习 {item.get('reps') or 0} 次，"
            f"到期 {item.get('due') or ''}）：{body}")
    lines.append("（按 FSRS 排期；引用错题写「错题 #编号」。）")
    return "\n".join(lines)


def get_mastery(days: int = 0, *, ctx: ToolContext) -> str:
    """知识点掌握度（BKT）摘要。"""
    days = max(0, min(int(days or 0), 3650))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        data = knowledge.attempt_stats(conn, days=days)
    except Exception as exc:
        return f"读知识点掌握度失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    meta = data.get("bkt") or {}
    min_samples = int(meta.get("min_samples") or 5)
    totals = data.get("totals") or {}
    points = [p for p in (data.get("points") or []) if p.get("kind") != "other"]
    if not points:
        return "还没有知识点记录。"
    lines = ["知识点掌握度（BKT）："]
    average = totals.get("average_mastery")
    lines.append(
        f"- 平均掌握度 {(average * 100):.0f}%，已建模 "
        f"{totals.get('mastery_ready_points') or 0}/{len(points)} 类"
        if average is not None else "- 还没有 ≥ "
        f"{min_samples} 条样本的类目，暂不建模")
    weakest = totals.get("weakest") or {}
    if weakest.get("name"):
        lines.append(
            f"- 最弱：{weakest['name']} "
            f"{float(weakest.get('mastery') or 0) * 100:.0f}%"
            f"（{weakest.get('attempts') or 0} 条样本）")
    lines.append("各类目：")
    for point in points:
        mastery = point.get("mastery")
        if mastery is None:
            lines.append(f"- {point['name']}：{point.get('mastery_level') or '样本不足'}"
                         f"（{point.get('mastery_attempts') or 0}/{min_samples}）")
        else:
            lines.append(
                f"- {point['name']}：{float(mastery) * 100:.0f}%"
                f"（{point.get('mastery_level') or ''}，"
                f"{point.get('mastery_attempts') or 0} 条样本）")
    lines.append("（样本不足的类目不参与平均；掌握度是训练信号，不是考试分数。）")
    return "\n".join(lines)


def get_train_summary(days: int = 30, *, ctx: ToolContext) -> str:
    """六级写作/翻译训练概况。"""
    days = max(7, min(int(days or 30), 365))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        plan = train_plan.plan(conn)
        stats = train_stats.stats(conn, days=days)
    except Exception as exc:
        return f"读训练概况失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    today = plan.get("today") or {}
    due = plan.get("due") or {}
    task = plan.get("task") or {}
    totals = stats.get("totals") or {}
    by_kind = stats.get("by_kind") or {}
    lines = [f"六级写作/翻译训练（近 {days} 天）："]
    lines.append(
        f"- 连续训练 {plan.get('streak') or 0} 天；今天：写作 {today.get('writing') or 0} / "
        f"翻译 {today.get('translation') or 0} / 一句一译 {today.get('sentence') or 0}")
    lines.append(
        f"- 到期错误卡 {due.get('total') or 0} 张"
        f"（写作 {due.get('writing') or 0} / 翻译 {due.get('translation') or 0}）")
    if task.get("title"):
        lines.append(f"- 今日任务：{task.get('title')}"
                     + (f" —— {task.get('detail')}" if task.get("detail") else ""))
    if not (totals.get("submissions") or 0) and not (totals.get("sentences") or 0):
        lines.append(f"- 近 {days} 天还没有已批改的写作/翻译提交。")
        return "\n".join(lines)
    lines.append(
        f"- 已批改：成篇 {totals.get('submissions') or 0} 篇、句译 {totals.get('sentences') or 0} 条、"
        f"{totals.get('minutes') or 0} 分钟")
    band_bits = []
    for kind, label in (("writing", "写作"), ("translation", "翻译")):
        entry = by_kind.get(kind) or {}
        if entry.get("avg_band") is not None:
            band_bits.append(f"{label}平均 {entry['avg_band']}"
                             f"（最近 {entry.get('last_band')}，最高 {entry.get('best_band')}）")
    if band_bits:
        lines.append("- " + "；".join(band_bits))
    trend = [row for row in (stats.get("band_trend") or []) if row.get("writing") is not None
             or row.get("translation") is not None][-7:]
    if trend:
        pieces = []
        for row in trend:
            writing = "–" if row.get("writing") is None else row["writing"]
            translation = "–" if row.get("translation") is None else row["translation"]
            pieces.append(f"{str(row.get('date'))[5:]} {writing}/{translation}")
        lines.append("- 最近档位（写作/翻译）：" + "，".join(pieces))
    errors = (stats.get("error_types") or [])[:5]
    if errors:
        lines.append("- 高频错误：" + "、".join(
            f"{item['type']} {item['count']}" for item in errors))
    lines.append("（只统计已批改提交；一句一译不计档位。）")
    return "\n".join(lines)


def list_recordings(query: str = "", limit: int = 10,
                    *, ctx: ToolContext) -> str:
    """本地录像列表。"""
    query = str(query or "").strip()
    limit = max(1, min(int(limit or 10), 30))
    conn = None
    try:
        conn = store.connect(ctx.db_path)
        items = store.list_recordings(conn, query=query, limit=limit)
    except Exception as exc:
        return f"读录像列表失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not items:
        if query:
            return f"没有找到转写里包含「{query}」的录像。"
        return "本地还没有录像。"
    lines = [f"最近的录像（最多 {limit} 段，新→旧）："]
    for item in items:
        seconds = float(item.get("duration") or 0)
        length = (f"{seconds / 60:.1f} 分钟" if seconds >= 60
                  else f"{seconds:.0f} 秒")
        lines.append(
            f"- #{item['id']} {item.get('started_at') or ''} ｜ {item.get('title') or ''} ｜ "
            f"{length} ｜ 转写 {item.get('transcripts') or 0} 段 / "
            f"{item.get('chars') or 0} 字"
            + (f"\n  开头：{item['preview']}" if item.get("preview") else ""))
    lines.append("（打开录像页：`#/recordings?session=<编号>`；"
                 "要正文用 search_records，kinds 选 transcripts。）")
    return "\n".join(lines)
