"""Agent 的读工具：查本地学习记录、今日概览、读挂载文档、对截图跑 OCR。

原则：
- **只读**。写操作（收藏、排复习、改档案）留到 P4，并且必须界面确认。
- 工具失败不抛给模型看裸异常，返回一句中文说明，让模型自己决定下一步。
- 路径只允许在数据根目录内（截图、录屏、附件都在那里），防止被提示词带到系统目录。
"""
from __future__ import annotations

import datetime
import pathlib
from dataclasses import dataclass, field

from learnsys import config, store
from learnsys.ask import study

TOOL_SCHEMAS = [
    {
        "name": "search_records",
        "description": (
            "搜索用户本地的学习记录：问答、课堂声音转写、屏幕快照 OCR 文字。"
            "当用户问「我之前问过什么」「老师刚才怎么讲的」「哪一节提到过 X」时使用。"
            "返回带时间和来源的片段；找不到就如实说找不到。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "关键词，中文即可；留空 = 看最近记录"},
                "days": {"type": "integer", "description": "只搜最近多少天，默认 7"},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["asks", "transcripts", "frames"]},
                    "description": "搜哪几类，默认全搜",
                },
                "limit": {"type": "integer", "description": "最多返回几条，默认 8"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "today_summary",
        "description": (
            "看用户今天的学习概况：录了多久、切换了多少次窗口、问答多少条、"
            "课堂转写了多少、错题本有几题待复习。用户问「我今天学了什么」时先用它。"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_attachment",
        "description": "读取用户当前挂载的课件/文档正文。分段读取，offset 是字符偏移。",
        "input_schema": {
            "type": "object",
            "properties": {
                "offset": {"type": "integer", "description": "从第几个字符开始，默认 0"},
            },
        },
    },
    {
        "name": "ocr_image",
        "description": "对数据目录里的一张截图做 OCR，返回识别出的文字。只能读数据目录内的图片。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片的绝对路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_materials",
        "description": (
            "在用户的资料库里搜课件和笔记，返回命中段、资料名和页码。"
            "用户问「课件里怎么讲的」「哪份资料提到过 X」时先用它；"
            "回答时标注资料名和页码，资料里没有就如实说没有。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，中文即可"},
                "limit": {"type": "integer", "description": "最多返回几条，默认 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_material",
        "description": (
            "按资料 id 顺序读正文，分段返回。offset 是字符偏移；"
            "先 search_materials 找到 id，再用它读上下文。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": {"type": "integer", "description": "资料 id"},
                "offset": {"type": "integer", "description": "从第几个字符开始，默认 0"},
                "length": {"type": "integer", "description": "读多少字符，默认 6000"},
            },
            "required": ["material_id"],
        },
    },
]


SAVE_WRONGBOOK_SCHEMA = {
    "name": "save_wrongbook",
    "description": (
        "把刚批改错的测验题收进错题本。只在用户答错或部分答错时调用；"
        "同一道题只调用一次，答对不要调用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string",
                         "description": "完整题目原文，不要改写，不要带【第N题】前缀"},
            "correct_answer": {"type": "string",
                               "description": "正确答案；不确定可留空"},
            "my_answer": {"type": "string",
                          "description": "用户这题的作答原文"},
            "tags": {"type": "string",
                     "description": "知识点标签，逗号分隔"},
        },
        "required": ["question", "correct_answer", "my_answer"],
    },
}


def schemas_for(mode: str = "explain", *, use_tools: bool = True):
    """按模式给工具清单：错题本只写工具只在测验里暴露。"""
    if not use_tools:
        return None
    schemas = list(TOOL_SCHEMAS)
    if mode == "quiz":
        schemas.append(SAVE_WRONGBOOK_SCHEMA)
    return schemas


@dataclass
class ToolContext:
    data_root: pathlib.Path
    attachment_name: str = ""
    attachment_text: str = ""
    db_path: pathlib.Path | None = None
    conversation_id: int | None = None
    conversation_key: str = ""
    mode: str = ""
    material_id: int = 0          # 从资料出题时带上，错题按资料归档
    saved: set[str] = field(default_factory=set)


def _one_line(text: str, cap: int = 300) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= cap else value[:cap] + "…"


def _stamp(value) -> str:
    text = str(value or "")
    return text[:16] if len(text) >= 16 else text


def _safe_path(raw: str, data_root: pathlib.Path) -> pathlib.Path | None:
    """只允许数据根目录里的文件 —— 防止工具被诱导去读系统目录。"""
    try:
        path = pathlib.Path(raw).expanduser().resolve()
        root = data_root.resolve()
        path.relative_to(root)
        return path
    except (OSError, ValueError):
        return None


def search_records(query: str, days: int = 7, kinds: list | None = None,
                   limit: int = 8, *, data_root: pathlib.Path | None = None) -> str:
    """跨天搜问答 / 转写 / 快照文字；结果按时间倒序。"""
    query = str(query or "").strip()
    days = max(1, min(int(days or 7), 90))
    limit = max(1, min(int(limit or 8), 20))
    wanted = set(kinds or ["asks", "transcripts", "frames"])
    root = pathlib.Path(data_root or config.DATA_ROOT)
    since = datetime.date.today() - datetime.timedelta(days=days)
    since_ts = since.isoformat() + " 00:00:00"
    # 空关键词不是错误：模型常拿它来「看最近记录」。LIKE '%%' 就是全匹配。
    pattern = f"%{query}%" if query else "%"
    what = f"和「{query}」相关" if query else ""
    found: list[tuple[str, str, str]] = []      # (ts, 来源, 正文)

    for day, db_path in study.storage_dbs(root):
        if day < since:
            continue
        try:
            conn = store.connect(db_path)
        except Exception:
            continue
        try:
            if "asks" in wanted:
                for ts, question, answer in conn.execute(
                        "SELECT ts, question, answer FROM asks "
                        "WHERE (question LIKE ? OR answer LIKE ?) AND ts >= ? "
                        "ORDER BY ts DESC LIMIT ?", (pattern, pattern, since_ts, limit)):
                    found.append((_stamp(ts), "问答",
                                  f"问：{_one_line(question, 160)}｜答：{_one_line(answer, 260)}"))
            if "transcripts" in wanted:
                for ts, text in conn.execute(
                        "SELECT ts_start, text FROM transcripts "
                        "WHERE text LIKE ? AND ts_start >= ? "
                        "ORDER BY ts_start DESC LIMIT ?", (pattern, since_ts, limit)):
                    found.append((_stamp(ts), "课堂转写", _one_line(text, 320)))
            if "frames" in wanted:
                for ts, text in conn.execute(
                        "SELECT ts, text FROM frame_text "
                        "WHERE text LIKE ? AND ts >= ? "
                        "ORDER BY ts DESC LIMIT ?", (pattern, since_ts, limit)):
                    found.append((_stamp(ts), "屏幕文字", _one_line(text, 320)))
        except Exception:
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if len(found) >= limit * 3:
            break

    if not found:
        return f"最近 {days} 天里没有{what}的学习记录。"

    found.sort(key=lambda item: item[0], reverse=True)
    lines = [f"最近 {days} 天里{what}的记录（新→旧，最多 {limit} 条）："]
    total = 0
    for ts, source, body in found[:limit]:
        line = f"[{source} {ts}] {body}"
        if total + len(line) > 6000:
            break
        lines.append(line)
        total += len(line)
    lines.append("（以上来自本地记录，可能不完整；没有提到的内容不要当成不存在，也不要编造。）")
    return "\n".join(lines)


def today_summary(*, data_root: pathlib.Path | None = None) -> str:
    """今天的学习概况。"""
    root = pathlib.Path(data_root or config.DATA_ROOT)
    today = datetime.date.today()
    day_text = today.isoformat()
    unified = root / "learning.db"
    if unified.exists():
        db_path = unified
    else:
        # 兼容 v1：还没迁移时读按天库
        db_path = root / f"{today.year}.{today.month}.{today.day}" / "learnsys.db"
    if not db_path.exists():
        return "今天还没有学习记录（没开录制，也没有问答）。"
    try:
        conn = store.connect(db_path)
    except Exception as exc:
        return f"读今天的记录失败：{exc}"
    try:
        stats = store.focus_stats(conn, day=day_text)
        ask_rows = store.recent_asks(conn, limit=5, day=day_text)
        ask_count = conn.execute(
            "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (f"{day_text}%",)).fetchone()[0]
        transcript_count, char_count = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts "
            "WHERE ts_start LIKE ?", (f"{day_text}%",)).fetchone()
        due = store.wrong_due_items(conn, today)
    except Exception as exc:
        return f"统计今天的记录失败：{exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass

    lines = [f"今天（{day_text}）的学习概况："]
    minutes = float(stats.get("分钟") or 0)
    lines.append(
        f"- 记录时长 {minutes:.0f} 分钟，切换窗口 {stats.get('切换', 0)} 次")
    apps = stats.get("程序") or []
    if apps:
        lines.append("- 最久停在：" + "、".join(
            f"{name} {mins:.0f} 分" for name, mins in apps[:3]))
    lines.append(f"- 问答 {int(ask_count)} 条（这里只列最近 5 条）")
    lines.append(f"- 课堂转写 {int(transcript_count)} 段 / {int(char_count)} 字")
    if due:
        lines.append(f"- 错题本有 {len(due)} 题到复习期了")
    for row in ask_rows:
        lines.append(f"  · [{_stamp(row[0])}] {_one_line(row[1], 100)}")
    return "\n".join(lines)


def read_attachment(offset: int = 0, *, ctx: ToolContext) -> str:
    """读挂载文档的一段。"""
    text = (ctx.attachment_text or "").strip()
    if not text:
        return "当前没有挂载文档。"
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    chunk = text[start:start + 4000]
    if not chunk:
        return f"文档已经读完了（共 {len(text)} 字）。"
    return (f"【文档：{ctx.attachment_name or '未命名'} · 第 {start}–{start + len(chunk)} 字 / "
            f"共 {len(text)} 字】\n{chunk}")


def ocr_image(path: str, *, ctx: ToolContext) -> str:
    """对数据目录里的图片做 OCR。"""
    safe = _safe_path(path, ctx.data_root)
    if safe is None:
        return "这个路径不在学习系统的数据目录里，不能读。"
    if not safe.exists():
        return f"图片不存在：{safe.name}"
    try:
        from learnsys.ask.ocr import ocr_image as _ocr
        text = _ocr(str(safe))
    except Exception as exc:
        return f"OCR 没成功：{exc}"
    if not text.strip():
        return "这张图里没有识别到文字。"
    return f"【OCR：{safe.name}】\n{text[:4000]}"


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
    head = (f"【{item['title']}】共 {len(body)} 字；"
            f"本次读 {offset}–{offset + len(piece)} 字")
    tail = "" if offset + len(piece) >= len(body) else (
        f"\n（后面还有 {len(body) - offset - len(piece)} 字，offset="
        f"{offset + len(piece)} 接着读）")
    return head + "\n" + piece + tail


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


def execute(name: str, args: dict, ctx: ToolContext) -> tuple[str, str]:
    """执行工具，返回 (给模型看的内容, 给界面看的一句话摘要)。"""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "search_records":
            text = search_records(
                str(args.get("query") or ""),
                int(args.get("days") or 7),
                args.get("kinds") if isinstance(args.get("kinds"), list) else None,
                int(args.get("limit") or 8),
                data_root=ctx.data_root,
            )
            return text, "查了本地学习记录"
        if name == "today_summary":
            return today_summary(data_root=ctx.data_root), "看了今天的学习概况"
        if name == "read_attachment":
            return read_attachment(int(args.get("offset") or 0), ctx=ctx), "读了挂载文档"
        if name == "ocr_image":
            return ocr_image(str(args.get("path") or ""), ctx=ctx), "对截图做了 OCR"
        if name == "search_materials":
            return (search_materials(str(args.get("query") or ""),
                                     int(args.get("limit") or 5), ctx=ctx),
                    "搜了资料库")
        if name == "read_material":
            return (read_material(int(args.get("material_id") or 0),
                                  int(args.get("offset") or 0),
                                  int(args.get("length") or 6000), ctx=ctx),
                    "读了资料正文")
        if name == "save_wrongbook":
            text = save_wrongbook(
                str(args.get("question") or ""), str(args.get("my_answer") or ""),
                str(args.get("correct_answer") or ""), str(args.get("tags") or ""),
                ctx=ctx)
            if text.startswith("已收进"):
                preview = "已收进错题本"
            elif text.startswith("这道题已经"):
                preview = "错题已在错题本"
            elif "失败" in text:
                preview = "错题本保存失败"
            else:
                preview = "没有收进错题本"
            return text, preview
    except Exception as exc:
        return f"工具执行失败：{exc}", "工具失败"
    return f"没有这个工具：{name}", "未知工具"
