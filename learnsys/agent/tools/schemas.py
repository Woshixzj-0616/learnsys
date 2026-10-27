"""工具清单与写操作摘要：模型看到什么、确认框显示什么，只在 schema 里定义一次。"""
from __future__ import annotations

from learnsys import knowledge
from learnsys.agent import sandbox


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


from .schemas_learning import (DUE_REVIEWS_SCHEMA, GET_MASTERY_SCHEMA,
                               GET_TRAIN_SUMMARY_SCHEMA, LIST_RECORDINGS_SCHEMA)
from .schemas_web import WEB_SCHEMAS
from .schemas_write import (ADD_VOCAB_SCHEMA, CET6_WRITE_SCHEMAS,
                            WRITE_LABELS_EXTRA, WRITING_WRITE_SCHEMAS,
                            WRITING_WRITE_TOOLS, extra_write_summary)

TOOL_SCHEMAS.extend([DUE_REVIEWS_SCHEMA, GET_MASTERY_SCHEMA,
                     GET_TRAIN_SUMMARY_SCHEMA, LIST_RECORDINGS_SCHEMA])


OPEN_FILE_SCHEMA = {
    "name": "open_file",
    "description": (
        "用系统默认程序打开本机的一个文件或文件夹（只接受绝对路径）。"
        "执行前会弹确认框，用户拒绝就不执行；不要声称已经打开。"
        "不能打开可执行文件、脚本、系统目录或网络共享路径。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "文件或文件夹的绝对路径，例如 D:\\课件\\网络.pdf"},
        },
        "required": ["path"],
    },
}

LAUNCH_APP_SCHEMA = {
    "name": "launch_app",
    "description": (
        "按名字启动开始菜单里能搜到的程序（例如「记事本」）。"
        "执行前会弹确认框，用户拒绝就不执行；找不到时返回候选程序名，不要猜。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "开始菜单里能搜到的程序名，例如「记事本」"},
        },
        "required": ["name"],
    },
}

OPEN_URL_SCHEMA = {
    "name": "open_url",
    "description": (
        "在工作台管理的独立浏览器窗口里打开一个 http/https 网址（新标签）。"
        "执行前会弹确认框，用户拒绝就不执行；不要声称已经打开。"
        "不能用它打开本地文件、执行脚本或控制页面。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string",
                    "description": "完整网址，例如 https://example.com"},
        },
        "required": ["url"],
    },
}

BROWSER_STATUS_SCHEMA = {
    "name": "browser_status",
    "description": (
        "看工作台浏览器是否在运行、当前标签的标题和网址。"
        "记录暂停时只会返回「已暂停」，不暴露当前页面。"
    ),
    "input_schema": {"type": "object", "properties": {}},
}

BROWSER_HISTORY_SCHEMA = {
    "name": "browser_history",
    "description": (
        "读工作台浏览器最近的访问记录（时间 / 标题 / 域名 / URL）。"
        "这些是用户本机浏览记录，只用于回答当前问题，不要主动扩散；"
        "最多返回 50 条。用户问「我最近看了什么网页」时使用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "最多返回几条，默认 20，上限 50"},
            "days": {"type": "integer", "description": "只看最近几天，默认 7；0 = 不限"},
        },
    },
}


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
                         "description": "完整题目原文，不要改写，不要带【第N题】前缀和【知识点】行"},
            "correct_answer": {"type": "string",
                               "description": "正确答案；不确定可留空"},
            "my_answer": {"type": "string",
                          "description": "用户这题的作答原文"},
            "tags": {"type": "string",
                     "description": "知识点类目，逗号分隔；只能从："
                                    + "、".join(knowledge.CATEGORY_NAMES)
                                    + " 中选 1–3 个"},
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
               "save_material_note", "write_study_file"} | WRITING_WRITE_TOOLS
# 需要用户确认的副作用工具：写数据 + 运行代码 + 动系统（打开文件/启动程序）。
# 打开文件/启动程序不改数据，但会在电脑上真的发生，所以单独放进确认集合、不进 WRITE_TOOLS。
CONFIRM_TOOLS = WRITE_TOOLS | {"run_code", "open_file", "launch_app", "open_url"}

WRITE_LABELS = {
    "save_wrongbook": "收进错题本",
    "save_memory": "写进长期记忆",
    "forget_memory": "删除长期记忆",
    "save_material_note": "保存资料笔记",
    "write_study_file": "写学习档案",
    "run_code": "运行代码",
    "open_file": "打开文件",
    "launch_app": "启动程序",
    "open_url": "打开网址",
    **WRITE_LABELS_EXTRA,
}

# 状态行给人看的短名（工具名本身不进界面）：网页与快捷栏共用这一份。
TOOL_LABELS = {
    **WRITE_LABELS,
    "make_plan": "列计划",
    "search_records": "查学习记录",
    "today_summary": "看今日概况",
    "recent_wrong_items": "读最近错题",
    "due_reviews": "查到期复习",
    "get_mastery": "查掌握度",
    "get_train_summary": "看训练概况",
    "list_recordings": "查录像",
    "get_cet6_context": "看六级进度",
    "search_materials": "查资料",
    "read_material": "读资料正文",
    "read_attachment": "读挂载文档",
    "ocr_image": "识别图片文字",
    "browser_status": "看浏览器状态",
    "browser_history": "查浏览记录",
    "web_search": "联网搜索",
    "fetch_url": "读取网页",
}


def label_for(name: str) -> str:
    """工具名 → 状态行中文短名；未知工具原样返回。"""
    return TOOL_LABELS.get(str(name or ""), str(name or ""))


def schemas_for(mode: str = "explain", *, use_tools: bool = True,
                surface: str = "ask"):
    """按入口和模式给工具清单。

    - 速答（quick）只留记忆工具：一两句话的任务不该带 20 多个工具；
    - 快捷栏 / 六级 / 录像：只给学习读取工具，不放本机文件、程序、代码执行；
    - 工作台问答页：完整清单（仍是唯一能打开文件/启动程序/跑代码的入口）；
    - 测验模式不暴露系统工具；错题本写工具只在测验里出现。
    """
    if not use_tools:
        return None
    surface = str(surface or "ask").lower()
    memory = [SAVE_MEMORY_SCHEMA, FORGET_MEMORY_SCHEMA]
    if mode == "quick":
        return list(memory)

    learning = [MAKE_PLAN_SCHEMA, RECENT_WRONG_ITEMS_SCHEMA]
    core = learning + list(TOOL_SCHEMAS)
    if surface == "cet6":
        return core + memory + [SAVE_MATERIAL_NOTE_SCHEMA] + CET6_WRITE_SCHEMAS
    if surface == "video":
        # 录像里只加词：收训练错题、评档都回六级/工作台做。
        return core + memory + [SAVE_MATERIAL_NOTE_SCHEMA, ADD_VOCAB_SCHEMA]
    if surface == "quickbar":
        # 课上只给「记一下这个词」；删除/评档会打断听讲。
        return core + memory + list(WEB_SCHEMAS) + [ADD_VOCAB_SCHEMA]

    schemas = list(core) + list(memory)
    if mode != "quiz":
        # 测验页不该顺手打开本机文件 / 程序 / 网页；只在工作台问答页暴露。
        schemas += (WEB_SCHEMAS
                    + [OPEN_FILE_SCHEMA, LAUNCH_APP_SCHEMA,
                       OPEN_URL_SCHEMA, BROWSER_STATUS_SCHEMA, BROWSER_HISTORY_SCHEMA])
        schemas += WRITING_WRITE_SCHEMAS
    schemas += [SAVE_MATERIAL_NOTE_SCHEMA, WRITE_STUDY_FILE_SCHEMA, RUN_CODE_SCHEMA]
    if mode == "quiz":
        schemas.append(SAVE_WRONGBOOK_SCHEMA)
    return schemas


def write_summary(name: str, args: dict) -> str:
    """写操作确认框里给人看的一句话。用户要能一眼看出会改什么。"""
    args = args if isinstance(args, dict) else {}
    extra = extra_write_summary(name, args)
    if extra:
        return extra
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
    if name == "open_file":
        # 确认框必须显示完整路径 —— 截断到看不出目标，就失去了确认的意义。
        return f"{label}：{str(args.get('path') or '').strip() or '（空路径）'}"
    if name == "launch_app":
        return f"{label}：{str(args.get('name') or '').strip() or '（空程序名）'}"
    if name == "open_url":
        # 完整网址不截断：确认框要让人看得出要去哪个网站。
        return f"{label}：{str(args.get('url') or '').strip() or '（空网址）'}"
    return label
