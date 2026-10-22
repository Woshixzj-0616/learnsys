"""Agent 的读工具：查本地学习记录、今日概览、读挂载文档、对截图跑 OCR。

原则：
- **只读**。写操作（收藏、排复习、改档案）留到 P4，并且必须界面确认。
- 工具失败不抛给模型看裸异常，返回一句中文说明，让模型自己决定下一步。
- 路径只允许在数据根目录内（截图、录屏、附件都在那里），防止被提示词带到系统目录。
"""
from __future__ import annotations

import datetime
import hashlib
import pathlib
from dataclasses import dataclass, field

from learnsys import config, store
from learnsys.agent import sandbox
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


GET_CET6_CONTEXT_SCHEMA = {
    "name": "get_cet6_context",
    "description": (
        "读取六级精听的当前进度：某份试卷 / Section / 题型单元的逐句标记、"
        "循环次数、完成状态和最近一次 AI 分析。用户问「我刚才循环的那句」"
        "「这段我标了什么」「上次分析怎么说」时使用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paper_id": {"type": "string", "description": "试卷 id；留空 = 最近一份"},
            "section": {"type": "string", "description": "Section 名称；留空 = 最近一段"},
            "item": {"type": "string", "description": "题型单元；留空 = 最近一段"},
            "limit": {"type": "integer", "description": "最多返回多少句，默认 40"},
        },
    },
}
TOOL_SCHEMAS.append(GET_CET6_CONTEXT_SCHEMA)


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


SAVE_MEMORY_SCHEMA = {
    "name": "save_memory",
    "description": (
        "把用户强调的**跨会话**偏好或规矩写进长期记忆（数据库，下一轮及以后都生效）。"
        "用户说「记住 / 以后 / 每次 / 永远 / 不要再 / 我习惯 / 回答用…」时必须先调用它。"
        "一条记忆只写一条独立规矩，写成完整句子；不要记这一题的临时要求或当天安排。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string",
                        "description": "完整的一句话，例如「回答和思考一律用中文」"},
            "kind": {"type": "string", "enum": ["preference", "rule", "identity"],
                     "description": "preference=偏好，rule=硬规矩，identity=关于用户的事实"},
        },
        "required": ["content"],
    },
}

FORGET_MEMORY_SCHEMA = {
    "name": "forget_memory",
    "description": (
        "删除一条长期记忆。用户说「忘掉那条 / 取消 / 以后不用…了」时调用；"
        "memory_id 用长期记忆列表里的编号。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "integer", "description": "要删除的记忆编号（# 后面的数字）"},
        },
        "required": ["memory_id"],
    },
}

MAKE_PLAN_SCHEMA = {
    "name": "make_plan",
    "description": (
        "复杂任务的计划。需要 2 次以上工具调用、或要跨问答记录 / 资料库 / 错题本"
        "多个来源时，**先调用它**再逐步执行；普通知识问题不要调用。"
        "最多 6 步，每一步写清做什么、准备用哪个工具。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string",
                                  "description": "这一步要做什么，一句话"},
                        "tool": {"type": "string",
                                 "description": "预计使用的工具名；不需要工具可留空"},
                    },
                    "required": ["title"],
                },
                "description": "2–6 步；按执行顺序排列",
            },
        },
        "required": ["steps"],
    },
}

RECENT_WRONG_ITEMS_SCHEMA = {
    "name": "recent_wrong_items",
    "description": (
        "读最近的错题（新→旧），返回错题编号、题目、正确答案、我的作答、标签和"
        "归档的资料名。用户问「我最近错了哪些题」「把错题找出来出变式」时先用它。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "最多返回几题，默认 8"},
            "days": {"type": "integer", "description": "只看最近几天；0 = 不限"},
            "material_id": {"type": "integer",
                            "description": "只看归档到这份资料的错题；0 = 不限"},
        },
    },
}

SAVE_MATERIAL_NOTE_SCHEMA = {
    "name": "save_material_note",
    "description": (
        "把整理好的笔记 / 代码讲解保存进资料库（会出现在「资料」页，可检索、可挂载）。"
        "用户说「把这段整理成资料 / 笔记存下来」时使用。保存前需要用户在界面上确认。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题，一句话"},
            "content": {"type": "string",
                        "description": "完整正文（Markdown 可以），最多 20 万字"},
            "tags": {"type": "string", "description": "标签，逗号分隔，可留空"},
        },
        "required": ["title", "content"],
    },
}

WRITE_STUDY_FILE_SCHEMA = {
    "name": "write_study_file",
    "description": (
        "把文本 / 代码文件写进数据目录的「学习档案」下（相对路径）。"
        "扩展名只支持 md/txt/cpp/cc/c/h/hpp/py/json/csv；写盘前需要用户确认。"
        "不要用它写资料库原文或系统目录。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "relative_path": {"type": "string",
                              "description": "相对「学习档案」的路径，例如 代码/栈示例.cpp"},
            "content": {"type": "string", "description": "文件内容，最多 20 万字"},
        },
        "required": ["relative_path", "content"],
    },
}

RUN_CODE_SCHEMA = {
    "name": "run_code",
    "description": (
        "在临时目录运行一段 C++ / C / Python 代码，带超时、内存和输出上限。"
        "**默认禁网**：代码里出现网络 API / 网址会被直接拒绝。"
        "用户说「跑一下 / 验证这段代码」时使用；只能读写自己的临时目录。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "language": {"type": "string", "enum": ["cpp", "c", "python"]},
            "code": {"type": "string", "description": "完整源代码"},
            "stdin": {"type": "string", "description": "可选的标准输入"},
        },
        "required": ["language", "code"],
    },
}

WRITE_TOOLS = {"save_wrongbook", "save_memory", "forget_memory",
               "save_material_note", "write_study_file"}
# 需要用户确认的副作用工具：写数据 + 运行代码（运行不算写，但同样要可见、可取消）
CONFIRM_TOOLS = WRITE_TOOLS | {"run_code"}

WRITE_LABELS = {
    "save_wrongbook": "收进错题本",
    "save_memory": "写进长期记忆",
    "forget_memory": "删除长期记忆",
    "save_material_note": "保存资料笔记",
    "write_study_file": "写学习档案",
    "run_code": "运行代码",
}


def schemas_for(mode: str = "explain", *, use_tools: bool = True):
    """按模式给工具清单：错题本只写工具只在测验里暴露；记忆工具所有模式都有。"""
    if not use_tools:
        return None
    schemas = [MAKE_PLAN_SCHEMA, RECENT_WRONG_ITEMS_SCHEMA] + list(TOOL_SCHEMAS)
    schemas += [SAVE_MEMORY_SCHEMA, FORGET_MEMORY_SCHEMA,
                SAVE_MATERIAL_NOTE_SCHEMA, WRITE_STUDY_FILE_SCHEMA, RUN_CODE_SCHEMA]
    if mode == "quiz":
        schemas.append(SAVE_WRONGBOOK_SCHEMA)
    return schemas


def write_summary(name: str, args: dict) -> str:
    """写操作确认框里给人看的一句话。用户要能一眼看出会改什么。"""
    args = args if isinstance(args, dict) else {}
    label = WRITE_LABELS.get(name, name)
    if name == "save_memory":
        content = " ".join(str(args.get("content") or "").split())[:120]
        return f"{label}：「{content}」"
    if name == "forget_memory":
        return f"{label}：编号 #{args.get('memory_id')}"
    if name == "save_wrongbook":
        question = " ".join(str(args.get("question") or "").split())[:80]
        return f"{label}：「{question}」"
    if name == "save_material_note":
        title = " ".join(str(args.get("title") or "").split())[:80]
        return f"{label}：「{title or '未命名笔记'}」"
    if name == "write_study_file":
        return f"{label}：学习档案/{str(args.get('relative_path') or '').strip()[:80]}"
    if name == "run_code":
        language = sandbox.normalize_language(args.get("language") or "")
        label_name = sandbox.LANGUAGES.get(language, {}).get("label", language)
        code = str(args.get("code") or "")
        first = next((line.strip() for line in code.splitlines() if line.strip()), "")
        return (f"{label}（{label_name}，{len(code.splitlines())} 行）"
                + (f"：{first[:60]}" if first else ""))
    return label


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
        return "这个路径不在学习工作台的数据目录里，不能读。"
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


STUDY_FILE_SUFFIXES = {".md", ".txt", ".cpp", ".cc", ".c", ".h", ".hpp",
                       ".py", ".json", ".csv"}
_STUDY_BAD_CHARS = set('<>:"|?*')


def _study_target(raw: str, data_root: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """把相对路径夹到「学习档案」里；拒绝绝对路径、`..` 和奇怪扩展名。"""
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return None, "没有给文件路径。"
    if text.startswith("/") or ":" in text:
        return None, "只能写「学习档案」里的相对路径，不能写绝对路径或盘符。"
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None, "只能写「学习档案」里的相对路径，不能包含 `..`。"
    if any(any(ch in _STUDY_BAD_CHARS for ch in part) or part.strip(".") == ""
           for part in parts):
        return None, "路径里有 Windows 不允许的字符。"
    suffix = pathlib.Path(parts[-1]).suffix.lower()
    if suffix not in STUDY_FILE_SUFFIXES:
        allowed = "、".join(sorted(STUDY_FILE_SUFFIXES))
        return None, f"不支持这个扩展名；只允许 {allowed}。"
    base = (pathlib.Path(data_root) / "学习档案").resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        return None, "只能写「学习档案」里的相对路径。"
    return target, ""


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


def write_study_file(relative_path: str, content: str, *,
                     ctx: ToolContext) -> str:
    """写「学习档案」下的文本文件；原子替换，失败给中文原因。"""
    body = str(content or "")
    if len(body) > 200_000:
        return "文件太长（上限 20 万字），没有保存。"
    target, reason = _study_target(relative_path, ctx.data_root)
    if target is None:
        return reason
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(body, encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        return f"写文件失败：{exc}"
    relative = target.relative_to((pathlib.Path(ctx.data_root) / "学习档案").resolve())
    return f"已保存到 学习档案/{relative.as_posix()}（{len(body)} 字）。"


def run_code(language: str, code: str, stdin: str = "",
             *, ctx: ToolContext) -> str:
    """在临时目录跑一段代码；结果（含失败原因）给模型和审计。"""
    result = sandbox.run(str(language or ""), str(code or ""),
                         stdin_text=str(stdin or ""))
    return result.render()


def execute(name: str, args: dict, ctx: ToolContext) -> tuple[str, str, bool]:
    """执行工具，返回 (给模型看的内容, 给界面看的一句话摘要, 是否成功)。

    `ok=False` 表示这次调用没拿到结果（参数错、库读失败、OCR 失败等）：
    内容仍原样回给模型换路，界面也会标红，不静默跳过。
    """
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
            return text, "查了本地学习记录", True
        if name == "today_summary":
            text = today_summary(data_root=ctx.data_root)
            ok = not text.startswith(("读今天的记录失败", "统计今天的记录失败"))
            return text, "看了今天的学习概况", ok
        if name == "recent_wrong_items":
            return (recent_wrong_items(int(args.get("limit") or 8),
                                       int(args.get("days") or 0),
                                       int(args.get("material_id") or 0), ctx=ctx),
                    "读了最近的错题", True)
        if name == "read_attachment":
            return read_attachment(int(args.get("offset") or 0), ctx=ctx), "读了挂载文档", True
        if name == "ocr_image":
            text = ocr_image(str(args.get("path") or ""), ctx=ctx)
            ok = not text.startswith(("这个路径不在", "图片不存在", "OCR 没成功"))
            return text, "对截图做了 OCR", ok
        if name == "search_materials":
            text = search_materials(str(args.get("query") or ""),
                                    int(args.get("limit") or 5), ctx=ctx)
            ok = not text.startswith(("搜索词是空的", "搜资料库失败"))
            return text, "搜了资料库", ok
        if name == "read_material":
            text = read_material(int(args.get("material_id") or 0),
                                 int(args.get("offset") or 0),
                                 int(args.get("length") or 6000), ctx=ctx)
            ok = not text.startswith(("读资料失败", "没有 id="))
            return text, "读了资料正文", ok
        if name == "get_cet6_context":
            return (get_cet6_context(
                str(args.get("paper_id") or ""), str(args.get("section") or ""),
                str(args.get("item") or ""), int(args.get("limit") or 40), ctx=ctx),
                "读了六级精听进度", True)
        if name == "save_material_note":
            text = save_material_note(
                str(args.get("title") or ""), str(args.get("content") or ""),
                str(args.get("tags") or ""), ctx=ctx)
            if text.startswith("已保存"):
                preview, ok = "保存了资料笔记", True
            elif "已经存在" in text:
                preview, ok = "资料库里已有这份内容", True
            else:
                preview, ok = "资料笔记没有保存", False
            return text, preview, ok
        if name == "write_study_file":
            text = write_study_file(
                str(args.get("relative_path") or ""),
                str(args.get("content") or ""), ctx=ctx)
            ok = text.startswith("已保存")
            return text, ("保存了学习档案文件" if ok else "学习档案没有保存"), ok
        if name == "run_code":
            result = sandbox.run(
                str(args.get("language") or ""), str(args.get("code") or ""),
                stdin_text=str(args.get("stdin") or ""))
            return result.render(), result.preview(), result.ok
        if name == "save_memory":
            text = save_memory(str(args.get("content") or ""),
                               str(args.get("kind") or "preference"), ctx=ctx)
            return text, ("记住了这条长期偏好" if text.startswith("已记住")
                          else "长期记忆已在" if text.startswith("这条已经")
                          else "长期记忆没保存"), text.startswith(("已记住", "这条已经"))
        if name == "forget_memory":
            text = forget_memory(int(args.get("memory_id") or 0), ctx=ctx)
            return text, ("忘掉了一条长期记忆" if text.startswith("已忘掉")
                          else "没找到那条记忆"), text.startswith("已忘掉")
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
            ok = text.startswith(("已收进", "这道题已经"))
            return text, preview, ok
    except Exception as exc:
        return f"工具执行失败：{exc}", "工具失败", False
    return f"没有这个工具：{name}", "未知工具", False
