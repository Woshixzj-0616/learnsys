"""批改文本的规范化与引用核对（唯一落点）。

批改结果的 `quote` 都经过这里：先按字形全角/引号/破折号归一，再精确匹配；
精确匹配失败时去掉标点与空白再比一次，防止句末标点差异误杀真引用。
"""
from __future__ import annotations

import re
import unicodedata

_LOOSE = re.compile(r"[^0-9a-z一-鿿]+")


def clip(value, cap: int = 2000) -> str:
    return str(value or "").strip()[:cap]


def normalized(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw or "").lower()
    for old, new in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                     ("—", "-"), ("–", "-")):
        value = value.replace(old, new)
    return " ".join(value.split())


def loose(raw: str) -> str:
    """去掉标点与空白，只比内容顺序。"""
    return _LOOSE.sub("", normalized(raw))


def quote_in_text(quote: str, text: str) -> bool:
    needle = normalized(quote)
    if not needle:
        return False
    haystack = normalized(text)
    if needle in haystack:
        return True
    loose_needle = loose(quote)
    if len(loose_needle) < 4:
        return False
    return loose_needle in loose(text)


def sentence_around(text: str, quote: str) -> str:
    """把 quote 扩成它在学生原文里的完整句子（确定性，不调模型）。

    找不到 quote 时退回 quote 本身——调用方仍能建卡，只是正面不完整。
    """
    text = str(text or "")
    quote = str(quote or "").strip()
    if not quote:
        return ""
    index = text.lower().find(quote.lower())
    if index < 0:
        return quote
    start = 0
    for pos in range(index - 1, -1, -1):
        if text[pos] in ".!?;":
            start = pos + 1
            break
    end = len(text)
    for pos in range(index + len(quote), len(text)):
        if text[pos] in ".!?":
            end = pos + 1
            break
    segment = text[start:end].strip()
    return segment or quote
