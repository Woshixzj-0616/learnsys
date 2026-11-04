"""复盘 / 测验 / 术语表的提示词拼装（口径唯一落点）。

提示词都在这里改；界面层只负责把数据搬进搬出。
"""
from __future__ import annotations

from learnsys import knowledge

from .context import _TRANSCRIPT_CAP

REVIEW_DISPLAY = "复盘：我刚才学了什么？"      # 上屏显示的那句（真正发给 AI 的题在 study 里拼）


def build_review_question(summary_lines: list[str], transcript_text: str,
                          frame_text: str = "") -> str:
    """复盘按钮发给 AI 的题：窗口摘要 + 转写正文 + 明确的输出要求。"""
    transcript_text = (transcript_text or "").strip()[-_TRANSCRIPT_CAP:]
    parts = [
        "以下是我今天在电脑上学习的自动记录（看过哪些窗口的摘要 + 老师讲话的声音转写）。",
        "请帮我复盘：①我主要在学什么；②列出最多 5 个值得记住的要点；",
        "③指出哪里看起来没学进去（比如长时间停在无关窗口）；④给我一个 10 分钟以内的复习建议。",
        "用纯文本，简洁，别复述记录本身。",
        "",
        "【窗口摘要】",
    ]
    parts += summary_lines or ["（这段没有窗口记录）"]
    if transcript_text:
        parts += ["", "【声音转写】", transcript_text]
    else:
        parts += ["", "【声音转写】（这段没有转写）"]
    return "\n".join(parts)


def _mastery_pct(value) -> str:
    return f"{int(float(value or 0) * 100)}%"


def _weak_focus_block(weak_points, focus: str) -> str:
    """「本轮重点」段：BKT 最弱类目 + 用户指定的焦点。都没有就返回空串。"""
    weak = [p for p in (weak_points or []) if p.get("name")]
    if not weak and not focus:
        return ""
    lines = ["【本轮重点】"]
    if weak:
        shown = "、".join(
            f"{p['name']} {_mastery_pct(p.get('mastery'))}"
            f"（{int(p.get('attempts') or 0)} 条答题）" for p in weak)
        lines.append(f"最近掌握度最低的类目：{shown}。")
        lines.append("出题时优先覆盖这些类目；今天的记录里没有相关素材时，"
                     "可以围绕同一主题延伸，但别硬凑。")
    if focus:
        lines.append(f"本轮指定重点：{focus}。5 道题里至少 3 道要考「{focus}」。")
    return "\n".join(lines)


def build_quiz_question(summary_lines: list[str], asks_preview: list[str],
                        transcript_text: str, weak_points: list[dict] | None = None,
                        focus: str = "") -> str:
    """测验按钮发给 AI 的题：基于今天的内容出 5 道自测题，逐题批改。

    `weak_points` 来自 BKT（`services.knowledge.weak_points`）；`focus` 必须已经过
    类目白名单校验，这里不再猜。
    """
    has_context = bool(summary_lines or asks_preview or (transcript_text or "").strip())
    only_weak = (not has_context) and bool(weak_points)
    parts = [
        ("我今天没有新的学习记录；请按下面的重点类目出题。"
         if only_weak else
         "以下是我今天学习的记录（窗口摘要 + 问过的问题 + 课堂转写）。"),
        "请基于这些内容出 **5 道自测题** 考我，要求：",
        "1. 只出题，先不要给答案；**一次只出一题**，每道题以「【第N题】」开头；",
        ("2. 题目围绕重点类目出通识自测题，别编造我今天学过什么；"
         if only_weak else
         "2. 题目从记录里的知识点来，别超纲；"),
        "3. 有简答也有选择；4. 我答一题你批一题，答错讲清楚错在哪；",
        "5. 只要我答错（含部分作答），先调用 save_wrongbook 工具："
        "question=题目原文（别改写，不要带【第N题】前缀和【知识点】行）、"
        "correct_answer=正确答案或关键解析、my_answer=我的原话、"
        "tags=本题【知识点】里的 1–3 个类目；然后再批改、出下一题。"
        "答对不要调用，同一题只调用一次。",
    ]
    focus_block = _weak_focus_block(weak_points, focus)
    if focus_block:
        parts += ["", focus_block]
    parts += [
        "",
        knowledge.prompt_rules(),
        "",
        "【窗口摘要】",
    ]
    parts += summary_lines or ["（今天没有新的学习记录）"]
    if asks_preview:
        parts += ["", "【今天问过的】"]
        parts += asks_preview
    if transcript_text:
        parts += ["", "【课堂转写】", transcript_text[-_TRANSCRIPT_CAP:]]
    return "\n".join(parts)


def _paged_preview(text: str, cap: int) -> tuple[str, bool]:
    """按页截取正文：PDF 的 `\\f` 换成「--- 第 N 页 ---」，超出 cap 截断。"""
    text = str(text or "")
    pages = text.split("\f") if "\f" in text else [text]
    pieces, used = [], 0
    truncated = False
    for index, page in enumerate(pages, 1):
        chunk = (f"--- 第 {index} 页 ---\n" if len(pages) > 1 else "") + page
        left = cap - used
        if left <= 0:
            truncated = True
            break
        if len(chunk) > left:
            pieces.append(chunk[:left])
            truncated = True
            break
        pieces.append(chunk)
        used += len(chunk)
    return "\n\n".join(pieces).strip(), truncated


def build_material_quiz_question(material: dict, cap: int = 12000) -> str:
    """从一份资料出题的提示词：只基于资料，一次一题；不够就 read_material 继续读。"""
    title = str(material.get("title") or "资料")
    body = str(material.get("body") or "")
    preview, truncated = _paged_preview(body, cap)
    size = f"{material.get('chars') or len(body)} 字"
    if material.get("pages"):
        size += f" / {material.get('pages')} 页"
    parts = [
        f"以下是我资料库里的《{title}》（资料 id={material.get('id')}，{size}）。",
        "请**只基于这份资料**出 **5 道自测题** 考我，要求：",
        "1. 只出题，先不要给答案；**一次只出一题**，每道题以「【第N题】」开头；",
        "2. 覆盖资料里的不同章节，优先定义、计算、易错点，别出资料里没有的内容；",
        "3. 有简答也有选择；我答一题你批一题；",
        "4. 如果给出的正文不够，调用 `read_material(material_id="
        f"{material.get('id')})` 继续读；找关键词也可以 `search_materials`；",
        "5. 只要我答错（含部分作答），先调用 save_wrongbook："
        "question=题目原文（不要带【第N题】前缀和【知识点】行）、"
        "correct_answer=正确答案或关键解析、my_answer=我的原话、"
        "tags=本题【知识点】里的 1–3 个类目；"
        "答对不要调用，同一题只调用一次。",
        "",
        knowledge.prompt_rules(),
        "",
        "【资料正文】",
        preview or "（这份资料还没有正文）",
    ]
    if truncated:
        parts += ["", f"（正文只给了前 {cap} 字，其余请用 read_material 继续读。）"]
    return "\n".join(parts)


def build_glossary_question(transcript_text: str, asks_preview: list[str]) -> str:
    """术语表：AI 从今天的转写+问答里提取学科术语。"""
    parts = [
        "以下是我今天学习的记录。请从中提取 **学科术语/关键词**，整理成一张术语表：",
        "每行一条，格式：术语 —— 一句话解释（解释要通俗，20 字以内）；",
        "只收学科相关的词，别收日常用语；按出现顺序排。",
        "",
    ]
    if asks_preview:
        parts += ["【问过的问题】"] + asks_preview + [""]
    if transcript_text:
        parts += ["【课堂转写】", transcript_text[-_TRANSCRIPT_CAP:]]
    return chr(10).join(parts)
