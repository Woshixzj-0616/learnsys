"""整篇翻译的复习卡：按题库段落建卡，正面永远中文。

拆出 `review.py` 是为了守住 500 行门禁；批改校验仍从 `review` 调用这里。
"""
from __future__ import annotations

import difflib
import hashlib

from .card_text import CARD_SEVERITIES, NON_CARD_TYPES, error_lines
from .textnorm import loose as _loose
from .textnorm import sentence_around


def translation_sentence_card(source_prefix: str, sentence: str,
                              rows: list[dict], my_answer: str = "", *,
                              question: str = "", source_id: str = "",
                              note: str = "") -> dict:
    """整篇翻译的整句卡；迁移脚本与批改落库共用这一种形状。

    `sentence` 是学生英文句（用于旧 source_id 与 my_answer 回退）；
    正面题面由 `question` 指定，整篇翻译传对应段落的中文原文。
    """
    digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:10]
    note_text = f"{len(rows)} 处必改 · 整句重译"
    if note:
        note_text += f" · {note}"
    return {
        "source": "translation",
        "source_id": source_id or f"{source_prefix}:{digest}",
        "question": question or sentence,
        "answer": "**必改**\n" + error_lines(rows),
        "my_answer": my_answer,
        "tags": "翻译 整句",
        "note": note_text,
        "auto": True,
    }


def _segment_for_quote(quote: str, text: str, alignment,
                       segments: list[dict]) -> tuple[int | None, bool]:
    """把一条错误 quote 定位到题库段落；返回 (段号, 是否为推断)。

    优先用批改结果里的 alignment（segment ↔ 学生译文片段），
    没有再拿学生整句与各段参考译文做相似度。
    """
    if not segments:
        return None, False
    needle = _loose(quote)
    if needle:
        for row in alignment or []:
            hay = _loose(row.get("quote"))
            if not hay:
                continue
            if needle in hay or hay in needle:
                try:
                    index = int(row.get("segment"))
                except (TypeError, ValueError):
                    continue
                if 1 <= index <= len(segments):
                    return index, False
    sentence = _loose(sentence_around(text, quote))
    best_index, best_ratio = 1, -1.0
    for index, segment in enumerate(segments, start=1):
        reference = _loose(segment.get("reference"))
        ratio = difflib.SequenceMatcher(None, sentence, reference).ratio()
        if ratio > best_ratio:
            best_index, best_ratio = index, ratio
    return best_index, best_ratio < 0.35


def _student_segment_text(alignment, index: int, text: str,
                          quote: str) -> str:
    for row in alignment or []:
        try:
            segment = int(row.get("segment"))
        except (TypeError, ValueError):
            continue
        if segment == index:
            value = str(row.get("quote") or "").strip()
            if value:
                return value
    return sentence_around(text, quote)


def translation_cards(pack: dict, text: str, errors: list[dict],
                      alignment=None) -> list[dict]:
    """整篇翻译：一个题库段落一张卡，正面是中文原文。

    学生英文放在背面 `my_answer`，复习时先看中文回译，再对照自己的译文。
    只有段落里至少有一处“严重”错误才建卡；一般错误仍列在背面。
    """
    segments = pack.get("segments") or []
    if not segments:
        # 兼容没有 segments 的旧题库/测试；正常整篇翻译都有中文意群。
        legacy: dict[str, list[dict]] = {}
        for row in errors:
            if row["type"] in NON_CARD_TYPES:
                continue
            legacy.setdefault(sentence_around(text, row["quote"]), []).append(row)
        return [translation_sentence_card(
                    f"translation:{pack.get('id')}", sentence, rows)
                for sentence, rows in legacy.items()
                if any(row["severity"] in CARD_SEVERITIES for row in rows)]
    groups: dict[int, list[dict]] = {}
    inferred: dict[int, bool] = {}
    for row in errors:
        if row["type"] in NON_CARD_TYPES:
            continue
        index, guess = _segment_for_quote(row["quote"], text, alignment, segments)
        if index is None:
            continue
        groups.setdefault(index, []).append(row)
        inferred[index] = inferred.get(index, False) or guess
    cards = []
    for index, rows in sorted(groups.items()):
        if not any(row["severity"] in CARD_SEVERITIES for row in rows):
            continue
        segment = segments[index - 1]
        question = str(segment.get("zh") or "").strip()
        if not question:
            continue
        student = _student_segment_text(alignment, index, text,
                                        rows[0]["quote"])
        cards.append(translation_sentence_card(
            f"translation:{pack.get('id')}", student, rows,
            my_answer=student, question=question,
            source_id=f"translation:{pack.get('id')}:seg{index}",
            note="段落对应为推断" if inferred[index] else ""))
    return cards
