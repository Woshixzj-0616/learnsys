"""CET-6 写作/翻译评分口径与硬规则（唯一落点）。

口径原则：
- 官方是**总体印象评分**：先定档，再在档内浮动；本项目只接受 0–15 整数档。
- 维度分只做画像，**不相加冒充官方分**。
- 硬规则与错误清单优先于档位：跑题、信息点大面积漏译会钳制上限。
- 模板检测只提示，不硬扣分。
"""
from __future__ import annotations

import re

BAND_TABLE: tuple[tuple[int, int, str, str], ...] = (
    (13, 15, "13–15 分", "切题，结构清晰，语言基本准确，表达较地道；偶有小错不影响理解。"),
    (10, 12, "10–12 分", "切题，结构较清楚，有少量明显错误；例证或衔接一般。"),
    (7, 9, "7–9 分", "基本切题，结构较松散，错误较多，部分句子影响理解。"),
    (4, 6, "4–6 分", "偏题或结构混乱，语言错误多，明显影响理解。"),
    (1, 3, "1–3 分", "严重偏题或几乎无法理解，只有零散正确表达。"),
    (0, 0, "0 分", "空白、完全跑题或无法辨认。"),
)

WRITING_DIMENSIONS = ("content", "structure", "language", "idiomatic")
TRANSLATION_DIMENSIONS = ("coverage", "accuracy", "fluency", "terminology")
DIMENSION_NAMES = {
    "content": "内容切题", "structure": "结构连贯",
    "language": "语言准确", "idiomatic": "表达地道",
    "coverage": "信息点覆盖", "accuracy": "准确性",
    "fluency": "通顺度", "terminology": "用词与术语",
}

# 只用来提示，不参与扣分。短语按最长优先匹配，避免重复计数。
TEMPLATE_PHRASES = (
    "with the rapid development of",
    "with the development of",
    "plays an increasingly important role",
    "it is widely acknowledged that",
    "there is no denying that",
    "it goes without saying that",
    "as far as i am concerned",
    "from my perspective",
    "every coin has two sides",
    "last but not least",
    "first and foremost",
    "on the one hand",
    "on the other hand",
    "in recent years",
    "more and more people",
    "as a matter of fact",
    "in my opinion",
    "to sum up",
    "in conclusion",
    "what's more",
    "from my point of view",
    "it is high time that",
    "only in this way can we",
    "there is a growing tendency",
    "catch up with the times",
)

SEVERITIES = ("严重", "一般", "建议")
WRITING_MIN_WORDS = 150
WRITING_SEVERE_MIN = 140
TRANSLATION_SOURCE_CHARS = (180, 200)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_CJK = re.compile(r"[一-鿿]")
_PHRASE = re.compile(
    r"\b(?:" + "|".join(re.escape(word).replace(r"\ ", r"\s+")
                        for word in sorted(TEMPLATE_PHRASES, key=len, reverse=True))
    + r")\b", re.I)


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def cjk_count(text: str) -> int:
    return len(_CJK.findall(text or ""))


def band_label(band: int) -> str:
    for low, high, label, _ in BAND_TABLE:
        if low <= band <= high:
            return label
    return "档位无效"


def band_descriptor(band: int) -> str:
    for low, high, _, desc in BAND_TABLE:
        if low <= band <= high:
            return desc
    return ""


def normalize_band(value) -> int | None:
    """接受 11 / 11.0 / "11"；越界或非数字返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    band = int(round(number))
    return band if 0 <= band <= 15 else None


def band_median(bands: list[int]) -> int | None:
    rows = sorted(b for b in bands if b is not None)
    if not rows:
        return None
    return rows[len(rows) // 2]


def template_check(text: str) -> dict:
    """模板短语命中：返回覆盖率与命中短语，只作提示。"""
    raw = text or ""
    total = len(_WORD.findall(raw))
    phrases: list[str] = []
    covered = 0
    for match in _PHRASE.finditer(raw):
        phrase = " ".join(match.group(0).lower().split())
        if phrase in phrases:
            continue
        phrases.append(phrase)
        covered += len(_WORD.findall(match.group(0)))
    ratio = round(covered / total, 3) if total else 0.0
    return {"ratio": ratio, "phrases": phrases[:12]}


def _flag(code: str, level: str, message: str) -> dict:
    return {"code": code, "level": level, "message": message}


def inspect(kind: str, text: str, pack_item: dict | None = None,
            flags: dict | None = None) -> dict:
    """程序侧硬检查：字数、分段、粘贴/离开、模板、译文长度。"""
    text = text or ""
    flags = flags if isinstance(flags, dict) else {}
    words = word_count(text)
    chars = cjk_count(text)
    template = template_check(text)
    rows: list[dict] = []
    if kind == "writing":
        if words < WRITING_SEVERE_MIN:
            rows.append(_flag("word_count", "严重",
                              f"只有 {words} 词，低于 140 词。"))
        elif words < WRITING_MIN_WORDS:
            rows.append(_flag("word_count", "一般",
                              f"只有 {words} 词，未到 150 词下限。"))
        paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        if len(paragraphs) < 2:
            rows.append(_flag("paragraphs", "一般", "没有分段。"))
        lead = " ".join(str((pack_item or {}).get("lead_sentence") or "").split())
        if lead and not " ".join(text.split()).startswith(lead):
            rows.append(_flag("lead_sentence", "一般",
                              "没有以给定首句开头，或未逐字照抄。"))
        if template["ratio"] >= 0.3:
            rows.append(_flag("template", "提示",
                              f"模板短语占 {template['ratio']:.0%}，换题盲写时留意。"))
    elif kind == "translation":
        source_chars = cjk_count(str((pack_item or {}).get("source_zh") or ""))
        ratio = round(words / chars, 2) if chars else 0.0
        if chars and (ratio < 0.35 or ratio > 1.2):
            rows.append(_flag("length", "提示",
                              f"英文 {words} 词 / 中文 {chars} 字，比例 {ratio} 异常。"))
        if source_chars and abs(chars - source_chars) > max(8, source_chars * 0.1):
            rows.append(_flag("length", "提示",
                              f"译文含 {chars} 个汉字，与原文 {source_chars} 字差距较大，确认是否漏译。"))
        if template["ratio"] >= 0.25:
            rows.append(_flag("template", "提示",
                              f"模板短语占 {template['ratio']:.0%}。"))
    pasted = int(flags.get("pasted_chars") or 0)
    if pasted >= 20:
        rows.append(_flag("paste", "一般", f"检测到粘贴 {pasted} 个字符。"))
    left = int(flags.get("left_seconds") or 0)
    if left >= 30:
        rows.append(_flag("left", "一般", f"限时中离开页面 {left} 秒。"))
    return {"word_count": words, "cjk_count": chars, "template": template,
            "flags": rows}


def missing_cap(missing: int, total: int) -> tuple[int | None, str]:
    """翻译信息点漏译钳制：≥40% 最高 5 档，≥20% 最高 8 档。"""
    if total <= 0:
        return None, ""
    ratio = missing / total
    if ratio >= 0.4:
        return 5, f"漏译 {missing}/{total} 个信息点（{ratio:.0%}），最高 5 分档。"
    if ratio >= 0.2:
        return 8, f"漏译 {missing}/{total} 个信息点（{ratio:.0%}），最高 8 分档。"
    return None, ""


def clamp_band(band: int, caps: list[tuple[int | None, str]]) -> tuple[int, str]:
    reason = ""
    for cap, why in caps:
        if cap is not None and band > cap:
            band = cap
            reason = why
    return band, reason
