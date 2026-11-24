"""问答 profile：工具白名单 + 按意图挂载。

这里只放**工具名**，不 import `tools.schemas`：
- `tools/profiles.py` 负责把名字解析成 schema 对象；
- 这样 `schemas.py` 不需要反向 import profile，避免循环依赖。

设计口径（P35.1）：
- 学习助手默认只带 9 个核心工具 + 2 个记忆工具；
- 工作/生活/系统工具不在问答里出现，保留在 work profile；
- 按意图追加只读/写入工具，避免每轮把 37 个 schema 全塞给模型。
"""
from __future__ import annotations

ASSISTANT_CORE = [
    "search_materials",
    "read_material",
    "search_records",
    "recent_wrong_items",
    "due_reviews",
    "list_vocab",
    "web_search",
    "fetch_url",
    "run_code",
]

ASSISTANT_MEMORY = ["save_memory", "forget_memory"]

# 快捷栏：轻量问答，不跑代码、不读长资料；只保留最常用的读工具。
ASSISTANT_QUICK = [
    "search_materials",
    "search_records",
    "recent_wrong_items",
    "due_reviews",
    "list_vocab",
    "web_search",
    "fetch_url",
    "save_memory",
]

READ_ON_DEMAND = {
    "get_mastery": ("弱", "掌握", "薄弱", "哪块"),
    "get_train_summary": ("写作", "翻译", "档位", "作文", "训练"),
    "today_summary": ("今天", "学了什么", "学习情况", "学习状态"),
    "get_cet6_context": ("六级", "精听", "听力", "循环", "断点", "这句", "这段"),
    "search_dialog_archive": ("以前", "之前问", "旧对话", "历史对话", "上次"),
    "search_local_files": ("本机", "电脑上", "pdf", "文件", "下载", "d盘", "桌面"),
    "read_local_file": ("本机", "电脑上", "pdf", "文件", "下载", "d盘", "桌面"),
    "list_recordings": ("录像", "录过", "课堂", "转写"),
    "make_plan": ("整理", "汇总", "对比", "计划", "步骤", "分别"),
}

WRITE_ON_DEMAND = {
    "save_wrongbook": ("收进复习", "记下这个错误", "错题"),
    "add_vocab": ("生词", "单词", "记一下这个词", "加进生词本"),
    "save_training_error": ("写作错误", "翻译错误", "收进训练", "训练错题"),
    "rate_review": ("记住了", "忘了", "有点模糊", "评一下", "评级"),
    "save_material_note": ("存成资料", "保存笔记", "整理成资料", "存到资料库"),
}

# 这些工具从学习问答里移除；保留在 work profile / 工作台入口。
REMOVED = {
    "open_file", "launch_app", "open_url", "browser_status", "browser_history",
    "life_cards", "life_items", "art_works", "travel_trace",
    "write_study_file", "delete_vocab",
}


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def tool_names(profile: str = "assistant", *, mode: str = "explain",
               message: str = "", has_image: bool = False,
               has_attachment: bool = False) -> list[str] | None:
    """返回该 profile 本轮可用工具名；未知 profile 返回 None（走旧逻辑）。"""
    profile = str(profile or "").lower()
    text = str(message or "").lower()
    if profile == "assistant.quick":
        names = list(ASSISTANT_QUICK)
        if _has(text, ("记一下这个词", "加进生词本", "生词")):
            names.append("add_vocab")
        return _dedupe(names)
    if profile not in ("assistant", "assistant.app"):
        return None

    names = list(ASSISTANT_CORE) + list(ASSISTANT_MEMORY)
    for tool, words in READ_ON_DEMAND.items():
        if _has(text, words):
            names.append(tool)
    for tool, words in WRITE_ON_DEMAND.items():
        if _has(text, words):
            names.append(tool)
    if mode == "quiz":
        names.append("save_wrongbook")
    if has_image:
        names.append("ocr_image")
    if has_attachment:
        names.append("read_attachment")
    return _dedupe(names)
