"""P25.2 学习写入工具：schema、标签、确认框文案。

单独成文件，避免 `schemas.py` 越过 500 行体量门禁；`schemas.py` 只做合并与分发。
"""
from __future__ import annotations

ADD_VOCAB_SCHEMA = {
    "name": "add_vocab",
    "description": (
        "把一个生词或短语加进生词本，并自动建复习卡（明天到期）。"
        "用户说「记一下这个词 / 加进生词本」时使用。"
        "同一个词只补空字段，不覆盖用户已经填好的释义；不要替用户编释义。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "word": {"type": "string", "description": "单词或短语，原样保留大小写"},
            "meaning": {"type": "string",
                        "description": "中文释义；用户没给就留空，不要猜"},
            "phonetic": {"type": "string", "description": "音标，可选"},
            "context": {"type": "string",
                        "description": "出现它的原句或上下文，可选"},
            "source": {"type": "string", "enum": ["agent", "cet6"],
                       "description": "来源，默认 agent"},
        },
        "required": ["word"],
    },
}

DELETE_VOCAB_SCHEMA = {
    "name": "delete_vocab",
    "description": (
        "从生词本删掉一个词（它的复习卡一起删）。一次只删一个。"
        "优先用 item_id；只有词形时用 word 精确匹配，找不到会返回相近词。"
        "删除前必须让用户确认。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "word": {"type": "string", "description": "要删的词；按精确词形匹配"},
            "item_id": {"type": "integer",
                        "description": "生词编号；有编号时优先用它"},
        },
    },
}

RATE_REVIEW_SCHEMA = {
    "name": "rate_review",
    "description": (
        "给一张到期的错题/生词卡评档：1 忘了 / 2 模糊 / 3 记得 / 4 简单。"
        "必须先用 due_reviews 或 recent_wrong_items 拿到 item_id，不要自己编号；"
        "一次只评一张，不要替用户批量评。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "item_type": {"type": "string", "enum": ["wrong", "vocab"],
                          "description": "wrong=错题，vocab=生词"},
            "item_id": {"type": "integer", "description": "卡片编号"},
            "rating": {"type": "integer", "enum": [1, 2, 3, 4],
                       "description": "1 忘了 / 2 模糊 / 3 记得 / 4 简单"},
            "item_label": {
                "type": "string",
                "description": "题干或单词，从读到的结果原样复制，只用于确认框展示",
            },
        },
        "required": ["item_type", "item_id", "rating"],
    },
}

SAVE_TRAINING_ERROR_SCHEMA = {
    "name": "save_training_error",
    "description": (
        "把六级的写作/翻译错误收进错题本并进复习队列。"
        "用户说「把这个错误收进复习」时使用。"
        "question 填原句或题目，my_answer 填用户原来的写法，"
        "correct_answer 填正确写法，skill 填知识点（如时态/主谓一致）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "原句或题目"},
            "my_answer": {"type": "string", "description": "用户原来的写法"},
            "correct_answer": {"type": "string", "description": "正确写法"},
            "skill": {"type": "string", "description": "知识点/技能，可选"},
            "source": {"type": "string", "enum": ["writing", "translation"],
                       "description": "写作或翻译，默认 writing"},
        },
        "required": ["question", "my_answer"],
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

WRITING_WRITE_SCHEMAS = [
    ADD_VOCAB_SCHEMA, DELETE_VOCAB_SCHEMA, RATE_REVIEW_SCHEMA,
    SAVE_TRAINING_ERROR_SCHEMA,
]

# 六级入口：加词、收训练错题、复习评档；删除仍只在工作台。
CET6_WRITE_SCHEMAS = [ADD_VOCAB_SCHEMA, SAVE_TRAINING_ERROR_SCHEMA,
                      RATE_REVIEW_SCHEMA]

WRITING_WRITE_TOOLS = {"add_vocab", "delete_vocab", "rate_review",
                       "save_training_error"}

WRITE_LABELS_EXTRA = {
    "add_vocab": "加进生词本",
    "delete_vocab": "删除生词",
    "rate_review": "复习评档",
    "save_training_error": "收进训练错题",
}

_RATING_NAMES = {1: "忘了", 2: "模糊", 3: "记得", 4: "简单"}


def _clip(text, cap: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= cap else value[:cap] + "…"


def extra_write_summary(name: str, args: dict) -> str:
    """四个新工具的确认框文案；不是它们就返回空串，交回 `schemas.write_summary`。"""
    args = args if isinstance(args, dict) else {}
    label = WRITE_LABELS_EXTRA.get(name)
    if not label:
        return ""
    if name == "add_vocab":
        word = _clip(args.get("word"), 60) or "（空）"
        meaning = _clip(args.get("meaning"), 60)
        return f"{label}：「{word}」" + (f" — {meaning}" if meaning else "")
    if name == "delete_vocab":
        word = _clip(args.get("word"), 60)
        item_id = args.get("item_id")
        target = f"生词 #{item_id}" if item_id else "生词"
        return f"{label}：{target}" + (f"「{word}」" if word else "")
    if name == "rate_review":
        kind = "错题" if str(args.get("item_type") or "") == "wrong" else "生词"
        item_label = _clip(args.get("item_label"), 40)
        try:
            rating = int(args.get("rating"))
        except (TypeError, ValueError):
            rating = 0
        shown = f"「{item_label}」" if item_label else ""
        return (f"{label}：{kind} #{args.get('item_id')}{shown}"
                f" · {_RATING_NAMES.get(rating, '?')}")
    question = _clip(args.get("question"), 60) or "（空）"
    return f"{label}：「{question}」"
