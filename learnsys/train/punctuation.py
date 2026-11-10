"""程序能确定的标点/空格问题：模型漏报或分类不稳时兜底。

只处理机械可判的四处：标点前多空格、标点后缺空格、句号后缺空格。
引用的片段对齐到词边界，并与模型已报的条目按内容重叠去重。
"""
from __future__ import annotations

import re

from .textnorm import loose

_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,;:])\s*")
_MISSING_SPACE_AFTER = re.compile(r"(?<=[,;:])(?=[A-Za-z])")
_MISSING_SPACE_AFTER_PERIOD = re.compile(r"(?<=[a-z.!?])(?=[A-Z])")


def _overlap(left: str, right: str) -> bool:
    a, b = loose(left), loose(right)
    if not a or not b:
        return False
    return a in b or b in a


def _snippet(text: str, start: int, end: int, pad: int = 12) -> str:
    """取命中点前后各一段、对齐到词边界的原文片段。"""
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    while right < len(text) and not text[right].isspace():
        right += 1
    return text[left:right].strip()


_MECHANICAL = (
    (_SPACE_BEFORE_PUNCT, "标点前多了空格",
     lambda value: _SPACE_BEFORE_PUNCT.sub(r"\1 ", value)),
    (_MISSING_SPACE_AFTER, "标点后缺空格",
     lambda value: _MISSING_SPACE_AFTER.sub(" ", value)),
    (_MISSING_SPACE_AFTER_PERIOD, "句号后缺空格",
     lambda value: _MISSING_SPACE_AFTER_PERIOD.sub(" ", value)),
)


def mechanical_errors(text: str, limit: int = 3) -> list[dict]:
    rows: list[dict] = []
    for pattern, why, fixer in _MECHANICAL:
        for match in pattern.finditer(text or ""):
            quote = _snippet(text, match.start(), match.end())
            fix = fixer(quote)
            if not quote or fix == quote:
                continue
            if any(_overlap(quote, row["quote"]) for row in rows):
                continue
            rows.append({"type": "标点", "severity": "建议", "quote": quote,
                         "fix": fix, "why": why, "gloss": ""})
            if len(rows) >= limit:
                return rows
    return rows


def with_mechanical(errors: list[dict], text: str, limit: int = 12) -> list[dict]:
    """补机械标点错；与模型已报的条目重叠就不重复加。

    模型自己填满 12 条时，优先顶掉末尾的「建议」而不是丢掉程序能确定的问题。
    """
    rows = list(errors)
    extra = [row for row in mechanical_errors(text, limit=limit)
             if not any(_overlap(row["quote"], old["quote"]) for old in rows)]
    for row in extra:
        if len(rows) >= limit:
            index = next((i for i in range(len(rows) - 1, -1, -1)
                          if rows[i].get("severity") == "建议"), len(rows) - 1)
            rows.pop(index)
        rows.append(row)
    return rows
