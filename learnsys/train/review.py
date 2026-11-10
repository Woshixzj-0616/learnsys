"""批改结果的程序侧校验（唯一落点）。

模型只负责“看出来”，这里负责“别让它乱说”：
- `quote` 必须在学生原文里能找到，找不到就丢弃，并计数上报；
- 档位只接受 0–15 整数；跑题/漏译按硬规则钳制；
- 多次评分取中位，档位差 >1 标记“不稳定”；
- 只有“严重”错误（单句为 must_fix）自动生成错误卡，其余留给用户手动收。
"""
from __future__ import annotations

import hashlib

from . import lexical, rubric
from .punctuation import with_mechanical
from .textnorm import clip as _text
from .textnorm import loose as _loose
from .textnorm import quote_in_text, sentence_around

MAX_ERRORS = 12
# 一条错误/一段对齐的引用都应是一两个片段；超长说明模型在复制整段，
# 截断会留下半截词，直接丢弃并计数更诚实。
MAX_QUOTE_CHARS = 300
MAX_ALIGN_CHARS = 360
CARD_SEVERITIES = ("严重",)
# 审题/结构问题无法“独立重练”成一张卡，只留在提交记录里（施工单 §3 铁律 3）。
NON_CARD_TYPES = ("结构", "审题")
_SENTENCE_CONCLUSIONS = ("准确", "基本准确", "有偏差", "误译")


def _severity(value) -> str:
    raw = str(value or "").strip()
    return raw if raw in rubric.SEVERITIES else "一般"


def filter_errors(raw, text: str, limit: int = MAX_ERRORS) -> tuple[list[dict], int]:
    """逐条核对 quote；伪造、过短或超长的引用直接丢弃。"""
    rows: list[dict] = []
    dropped = 0
    seen: set[tuple[str, str]] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        raw_quote = str(item.get("quote") or "").strip()
        if len(raw_quote) > MAX_QUOTE_CHARS:
            dropped += 1
            continue
        quote = _text(raw_quote, MAX_QUOTE_CHARS)
        if not quote_in_text(quote, text):
            dropped += 1
            continue
        fix = _text(item.get("fix"), 400)
        key = (_loose(quote), _loose(fix))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "type": _text(item.get("type") or "用词", 20),
            "severity": _severity(item.get("severity")),
            "quote": quote,
            "fix": fix,
            "why": _text(item.get("why"), 400),
            "gloss": _text(item.get("gloss"), 60),
        })
        if len(rows) >= limit:
            break
    return rows, dropped


def _dimensions(raw, keys) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in keys:
        try:
            value = int(round(float(raw.get(key))))
        except (TypeError, ValueError):
            out[key] = None
            continue
        out[key] = max(0, min(5, value))
    return out


def _band(raw) -> int | None:
    return rubric.normalize_band(raw)


def _band_reason(obj: dict, band: int | None) -> str:
    reason = _text(obj.get("band_reason"), 500)
    if reason:
        return reason
    return rubric.band_descriptor(band) if band is not None else ""


def _priorities(raw) -> list[str]:
    rows = []
    for item in raw if isinstance(raw, list) else []:
        value = _text(item, 300)
        if value:
            rows.append(value)
        if len(rows) >= 3:
            break
    return rows


def error_lines(errors: list[dict]) -> str:
    lines = []
    for row in errors:
        line = f"- `{row['quote']}` → **{row['fix']}**"
        if row.get("why"):
            line += f"：{row['why']}"
        lines.append(line)
    return "\n".join(lines)


def _writing_cards(pack: dict, errors: list[dict]) -> list[dict]:
    """写作仍按错误点建卡：作文的错误多在半句/短语，独立重练更有效。"""
    rows = []
    for index, row in enumerate(errors, start=1):
        if row["type"] in NON_CARD_TYPES:
            continue
        if row["severity"] not in CARD_SEVERITIES:
            continue
        digest = hashlib.sha1(
            f"{row['quote']}\n{row['fix']}".encode("utf-8")).hexdigest()[:10]
        rows.append({
            "source": "writing",
            "source_id": f"writing:{pack.get('id')}:{index}:{digest}",
            "question": f"改错：{row['quote']}",
            "answer": row["fix"],
            "my_answer": row["quote"],
            "tags": f"{row['type']} 写作",
            "note": row["why"],
            "auto": True,
        })
    return rows


def translation_sentence_card(source_prefix: str, sentence: str,
                              rows: list[dict], my_answer: str = "") -> dict:
    """整篇翻译的整句卡；迁移脚本与批改落库共用这一种形状。"""
    digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:10]
    return {
        "source": "translation",
        "source_id": f"{source_prefix}:{digest}",
        "question": sentence,
        "answer": "**必改**\n" + error_lines(rows),
        "my_answer": my_answer,
        "tags": "翻译 整句",
        "note": f"{len(rows)} 处必改 · 整句重译",
        "auto": True,
    }


def _translation_cards(pack: dict, text: str, errors: list[dict]) -> list[dict]:
    """整篇翻译：一个完整句子一张卡，该句全部错误点放在背面。

    只有句子里至少有一处“严重”错误才建卡；一般错误仍列在背面，
    让复习时能看到完整语境，但不额外增加卡量。
    """
    groups: dict[str, list[dict]] = {}
    for row in errors:
        if row["type"] in NON_CARD_TYPES:
            continue
        groups.setdefault(sentence_around(text, row["quote"]), []).append(row)
    cards = []
    for sentence, rows in groups.items():
        if not any(row["severity"] in CARD_SEVERITIES for row in rows):
            continue
        cards.append(translation_sentence_card(
            f"translation:{pack.get('id')}", sentence, rows))
    return cards


def sentence_card(item: dict, text: str, must_fix: list[dict],
                  minimal_fix: str) -> dict:
    """一句一译：中文原句一张卡，整句重译，背面列全部必改点。"""
    parts = []
    if item.get("reference"):
        parts.append(f"**参考译文**：{item['reference']}")
    parts.append("**必改**\n" + error_lines(must_fix))
    if minimal_fix:
        parts.append(f"**最小改动版**：{minimal_fix}")
    return {
        "source": "translation",
        "source_id": f"sentence:{item.get('id')}",
        "question": item.get("zh") or "",
        "answer": "\n\n".join(parts),
        "my_answer": text,
        "tags": "翻译 整句",
        "note": f"{len(must_fix)} 处必改 · 整句重译",
        "auto": True,
    }


def _vocab_cards(errors: list[dict], terms=None) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for row in errors:
        entry = lexical.as_vocab_entry(
            error_type=row.get("type", ""), quote=row.get("quote", ""),
            fix=row.get("fix", ""), why=row.get("why", ""),
            gloss=row.get("gloss", ""), terms=terms)
        if entry is None:
            continue
        word, meaning = entry
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"word": word, "meaning": meaning,
                     "quote": row.get("quote", ""), "why": row.get("why", "")})
    return rows


def validate_writing(obj: dict, text: str, pack: dict,
                     flags: dict | None = None,
                     hard: dict | None = None) -> dict:
    hard = hard or rubric.inspect("writing", text, pack, flags)
    band = _band(obj.get("band"))
    caps: list[tuple[int | None, str]] = []
    if bool(obj.get("off_topic")):
        caps.append((5, "判定跑题，最高 5 分档。"))
    reason = _band_reason(obj, band)
    if band is not None:
        band, cap_reason = rubric.clamp_band(band, caps)
        if cap_reason:
            reason = f"{reason} {cap_reason}".strip()
    errors, dropped = filter_errors(obj.get("errors"), text)
    errors = with_mechanical(errors, text, MAX_ERRORS)
    template = hard.get("template") or rubric.template_check(text)
    return {
        "kind": "writing",
        "prompt_id": pack.get("id"),
        "content_version": pack.get("content_version"),
        "band": band,
        "band_label": rubric.band_label(band) if band is not None else "",
        "band_reason": reason,
        "off_topic": bool(obj.get("off_topic")),
        "dimensions": _dimensions(obj.get("dimensions"),
                                  rubric.WRITING_DIMENSIONS),
        "errors": errors,
        "errors_dropped": dropped,
        "priorities": _priorities(obj.get("priorities")),
        "rewrite_task": _text(obj.get("rewrite_task"), 600),
        "template": template,
        "hard_rules": hard,
        "cards": _writing_cards(pack, errors),
        "vocab_cards": [],
    }


def _info_points(raw, pack: dict) -> dict:
    table = {row.get("id"): row for row in pack.get("info_points") or []}
    total = len(table)
    if not isinstance(raw, dict):
        return {"total": total, "covered": None, "missing": [],
                "missing_points": [], "notes": "", "known": False}
    seen: list[str] = []
    for key in raw.get("missing") or []:
        value = str(key or "").strip()
        if value in table and value not in seen:
            seen.append(value)
    return {
        "total": total,
        "covered": total - len(seen),
        "missing": seen,
        "missing_points": [table[key].get("zh", "") for key in seen],
        "notes": _text(raw.get("notes"), 500),
        "known": True,
    }


def _fits_segment(quote: str, segment: dict | None) -> bool:
    """对齐片段不能明显超过该意群的参考译文长度（防止模型整段复制）。"""
    ref_words = len(str((segment or {}).get("reference") or "").split())
    if not ref_words:
        return True
    return len(quote.split()) <= max(30, int(ref_words * 3.0) + 10)


def _alignment(raw, text: str, segments: list[dict]) -> tuple[list[dict], int]:
    """逐句对照：模型给意群编号 + 学生译文片段；片段必须能在原文找到。

    超长片段（模型复制整段）直接丢弃并计数，不做截断——截断会留下半截词。
    """
    rows: list[dict] = []
    dropped = 0
    seen: set[int] = set()
    count = len(segments or [])
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            segment = int(item.get("segment"))
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not 1 <= segment <= count or segment in seen:
            dropped += 1
            continue
        quote = str(item.get("quote") or "").strip()
        if (not quote or len(quote) > MAX_ALIGN_CHARS
                or not _fits_segment(quote, segments[segment - 1])
                or not quote_in_text(quote, text)):
            dropped += 1
            continue
        seen.add(segment)
        rows.append({"segment": segment, "quote": quote})
    rows.sort(key=lambda row: row["segment"])
    return rows, dropped


def validate_translation(obj: dict, text: str, pack: dict,
                         flags: dict | None = None,
                         hard: dict | None = None) -> dict:
    hard = hard or rubric.inspect("translation", text, pack, flags)
    band = _band(obj.get("band"))
    points = _info_points(obj.get("info_points"), pack)
    caps: list[tuple[int | None, str]] = []
    if points["known"]:
        cap, why = rubric.missing_cap(len(points["missing"]), points["total"])
        if cap is not None:
            caps.append((cap, why))
    reason = _band_reason(obj, band)
    if band is not None:
        band, cap_reason = rubric.clamp_band(band, caps)
        if cap_reason:
            reason = f"{reason} {cap_reason}".strip()
    errors, dropped = filter_errors(obj.get("errors"), text)
    errors = with_mechanical(errors, text, MAX_ERRORS)
    segments = pack.get("segments") or []
    alignment, alignment_dropped = _alignment(obj.get("alignment"), text,
                                              segments)
    return {
        "kind": "translation",
        "prompt_id": pack.get("id"),
        "content_version": pack.get("content_version"),
        "band": band,
        "band_label": rubric.band_label(band) if band is not None else "",
        "band_reason": reason,
        "dimensions": _dimensions(obj.get("dimensions"),
                                  rubric.TRANSLATION_DIMENSIONS),
        "info_points": points,
        "alignment": alignment,
        "alignment_missing": max(0, len(segments) - len(alignment)),
        "alignment_dropped": alignment_dropped,
        "errors": errors,
        "errors_dropped": dropped,
        "priorities": _priorities(obj.get("priorities")),
        "rewrite_task": _text(obj.get("rewrite_task"), 600),
        "template": hard.get("template") or rubric.template_check(text),
        "hard_rules": hard,
        "cards": _translation_cards(pack, text, errors),
        "vocab_cards": _vocab_cards(errors, pack.get("terms")),
    }


def _variants(item: dict, raw) -> list[str]:
    rows: list[str] = []
    for value in list(item.get("variants") or []) + list(raw or []):
        text = _text(value, 500)
        if text and text not in rows:
            rows.append(text)
        if len(rows) >= 3:
            break
    return rows


def validate_sentence(obj: dict, text: str, item: dict) -> dict:
    conclusion = str(obj.get("conclusion") or "").strip()
    if conclusion not in _SENTENCE_CONCLUSIONS:
        conclusion = "有偏差"
    raw_points = obj.get("info_points")
    raw_points = raw_points if isinstance(raw_points, dict) else {}
    try:
        total = int(raw_points.get("total") or len(item.get("info_points") or []))
    except (TypeError, ValueError):
        total = len(item.get("info_points") or [])
    total = max(total, 0)
    try:
        covered = int(raw_points.get("covered"))
    except (TypeError, ValueError):
        covered = None
    if covered is None:
        covered = total
    covered = max(0, min(total, covered))
    missing = [_text(x, 200) for x in (raw_points.get("missing") or [])
               if _text(x, 200)]
    must_fix, dropped = filter_errors(obj.get("must_fix"), text, limit=6)
    suggestions, sug_dropped = filter_errors(obj.get("suggestions"), text,
                                             limit=6)
    minimal_fix = _text(obj.get("minimal_fix"), 800)
    cards = [sentence_card(item, text, must_fix, minimal_fix)] if must_fix else []
    return {
        "kind": "sentence",
        "sentence_id": item.get("id"),
        "source_id": item.get("source_id", ""),
        "skill": item.get("skill", ""),
        "conclusion": conclusion,
        "info_points": {"total": total, "covered": covered, "missing": missing},
        "must_fix": must_fix,
        "suggestions": suggestions,
        "errors_dropped": dropped + sug_dropped,
        "reference": item.get("reference", ""),
        "variants": _variants(item, obj.get("variants")),
        "minimal_fix": minimal_fix,
        "idiomatic": _text(obj.get("idiomatic"), 800),
        "cards": cards,
        "vocab_cards": _vocab_cards(must_fix),
    }


def _merge_alignment(result: dict, samples: list[dict]) -> None:
    """对齐与档位无关：三份样本按意群取并集，base 的条目优先。"""
    if "alignment" not in result:
        return
    segment_count = (len(result.get("alignment") or [])
                     + int(result.get("alignment_missing") or 0))
    merged: dict[int, dict] = {}
    for sample in [result] + list(samples):
        for row in sample.get("alignment") or []:
            try:
                segment = int(row.get("segment"))
            except (TypeError, ValueError):
                continue
            merged.setdefault(segment, row)
    result["alignment"] = [merged[key] for key in sorted(merged)]
    result["alignment_missing"] = max(0, segment_count - len(merged))
    result["alignment_dropped"] = sum(
        int(sample.get("alignment_dropped") or 0) for sample in samples)


def merge_reviews(samples: list[dict], kind: str) -> dict:
    """三次评分取中位；base 取档位等于中位的那一份，错误清单跟着它。"""
    valid = [row for row in samples if row.get("band") is not None]
    if not valid:
        raise ValueError("模型没有给出有效档位")
    bands = [int(row["band"]) for row in valid]
    median = rubric.band_median(bands)
    spread = max(bands) - min(bands)
    base = next((row for row in valid if row["band"] == median), valid[0])
    result = dict(base)
    _merge_alignment(result, valid)
    result["stability"] = {
        "bands": bands, "spread": spread, "stable": spread <= 1,
        "samples": len(samples),
    }
    if spread > 1:
        result["band_reason"] = (
            f"{result.get('band_reason', '')}（三次评分不稳定，相差 {spread} 档；"
            "档位仅供参考）").strip()
    return result


def validate(kind: str, obj: dict, text: str, pack_item: dict,
             flags: dict | None = None) -> dict:
    if kind == "writing":
        return validate_writing(obj, text, pack_item, flags)
    if kind == "translation":
        return validate_translation(obj, text, pack_item, flags)
    if kind == "sentence":
        return validate_sentence(obj, text, pack_item)
    raise ValueError(f"未知批改类型：{kind}")
