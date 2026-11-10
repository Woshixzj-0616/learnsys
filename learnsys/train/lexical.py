"""生词本准入：只有词条进生词本，句子级问题进整句错题卡。

判断只看模型给出的错误类型和改后文本的形态，不做语义猜测：

- 拼写：只收单个单词；
- 搭配 / 术语 / 用词 / 词汇：收 1–4 词的固定搭配；
- 语法 / 标点 / 结构 / 漏译 / 误译 / 改变原意 / 中式英语：一律不收，
  因为它们依赖整句语境，应该由调用方生成整句错题卡。

改后文本含句内标点（逗号、句号、分号、问号、感叹号、顿号）或超过 4 词，
也不收——那已经是一个句子片段。
"""
from __future__ import annotations

import re

MAX_WORDS = 4
# 拼写纠正只收单词；搭配/术语最多 4 词；历史数据没有错误类型时只按 3 词形态判断。
MAX_SPELLING_WORDS = 1
MAX_SHAPE_WORDS = 4

_SENTENCE_PUNCT = re.compile(r"[，,。.；;！!？?、]")
_CJK = re.compile("[一-鿿]")
_VOCAB_TYPES = ("搭配", "术语", "用词", "词汇")
_MODALS = {"should", "would", "could", "must", "can", "may", "might",
           "will", "shall"}
_AUX = {"is", "are", "was", "were", "has", "have", "had", "do", "does",
        "did", "be", "been", "being"}
_DETERMINERS = {"the", "a", "an", "this", "that", "these", "those"}
_SUBJECT_LIKES = _DETERMINERS | {"some", "many", "each", "every", "all",
                                 "both", "no"}
_PARTICLES = {"only", "just", "even", "also", "still", "already", "never",
              "always", "often", "sometimes", "not"}
_CONJUNCTIONS = {"and", "or", "but", "because", "since", "after", "before",
                 "until", "when", "while", "although", "though", "if"}
# 这些错误类型离开整句就没有意义，出现任意一个就不进生词本。
_SENTENCE_TYPES = ("语法", "标点", "结构", "漏译", "误译", "改变原意", "中式英语")


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def as_vocab_entry(*, error_type: str, quote: str = "", fix: str = "",
                   why: str = "", gloss: str = "",
                   terms=None) -> tuple[str, str] | None:
    """把一条改错判成生词本词条；不是词条返回 None。

    返回 `(word, meaning)`，与 `store.add_vocab` 的录入方向一致：
    英文词头 + 中文释义。释义来源固定为「模型 gloss → 题库术语表」，
    两者都没有就不入本——`why` 是错因说明，不能冒充释义。
    """
    word = _clean(fix)
    if not word or word == _clean(quote):
        return None
    if _CJK.search(word) or _SENTENCE_PUNCT.search(word):
        return None
    words = word.split()
    kind = str(error_type or "")
    if "拼写" in kind:
        if len(words) > MAX_SPELLING_WORDS:
            # 多词「拼写」只有题库术语表认它才收（如 eletronic payment）。
            term_meaning = _term_meaning(word, terms)
            return (word, term_meaning) if term_meaning else None
        meaning = _meaning(gloss, why, word, terms)
        return (word, meaning) if meaning else None
    if any(token in kind for token in _SENTENCE_TYPES):
        return None
    if not any(token in kind for token in _VOCAB_TYPES):
        return None
    if len(words) > MAX_WORDS:
        return None
    meaning = _meaning(gloss, why, word, terms)
    return (word, meaning) if meaning else None


def _meaning(gloss: str, why: str, word: str, terms=None) -> str | None:
    note = _clean(why)
    gloss = _clean(gloss)
    if gloss and _CJK.search(gloss) and len(gloss) <= 40:
        return f"{gloss}｜{note}" if note and note != gloss else gloss
    return _term_meaning(word, terms)


def _norm_term(text: str) -> str:
    value = " ".join(str(text or "").lower().split())
    value = re.sub(r"^(?:the|a|an)\s+", "", value)
    if len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]
    return value


def _term_meaning(word: str, terms) -> str | None:
    """题库术语表里已有的中文；`en` 允许写成 `a / b` 的多译法。"""
    target = _norm_term(word)
    if not target:
        return None
    for row in terms or []:
        if not isinstance(row, dict):
            continue
        for option in re.split(r"\s*/\s*", str(row.get("en") or "")):
            if _norm_term(option) == target:
                meaning = _clean(row.get("zh"))
                if meaning:
                    return meaning
    return None


def is_lexical_shape(text: str) -> bool:
    """只按形态判断历史条目（旧数据没有可信的错误类型时用）。

    保守口径：1–4 词、无句内标点、无中文，并且不像主谓片段：
    - 含情态动词（should/would…）；
    - 以连词或副词性小品词开头（and/but/only/just…）；
    - 以 be/have/do 开头且第二词不是限定词（has shrunk / is different）；
    - 限定词/数量词开头且句中含助动词（The government has invested）；
    - 限定词开头、末词是小写 -s 结尾的谓语（The research demonstrates）。
    """
    word = _clean(text)
    if not word or _CJK.search(word) or _SENTENCE_PUNCT.search(word):
        return False
    words = word.split()
    if not 1 <= len(words) <= MAX_SHAPE_WORDS:
        return False
    lower = [item.lower() for item in words]
    if any(item in _MODALS for item in lower):
        return False
    if lower[0] in _CONJUNCTIONS or lower[0] in _PARTICLES:
        return False
    if len(words) >= 2 and lower[0] in _AUX and lower[1] not in _DETERMINERS:
        return False
    if (lower[0] in _SUBJECT_LIKES
            and any(item in _AUX for item in lower[1:])):
        return False
    if (len(words) >= 3 and lower[0] in _DETERMINERS
            and words[-1].islower() and words[-1].endswith("s")):
        return False
    return True
