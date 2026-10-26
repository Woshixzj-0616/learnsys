"""批改结果的程序侧校验（唯一落点）。

模型只负责“看出来”，这里负责“别让它乱说”：
- `quote` 必须在学生原文里能找到，找不到就丢弃，并计数上报；
- 档位只接受 0–15 整数；跑题/漏译按硬规则钳制；
- 多次评分取中位，档位差 >1 标记“不稳定”；
- 只有“严重”错误（单句为 must_fix）自动生成错误卡，其余留给用户手动收。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from . import rubric

MAX_ERRORS = 12
CARD_SEVERITIES = ("严重",)
# 审题/结构问题无法“独立重练”成一张卡，只留在提交记录里（施工单 §3 铁律 3）。
NON_CARD_TYPES = ("结构", "审题")
_SENTENCE_CONCLUSIONS = ("准确", "基本准确", "有偏差", "误译")
_LOOSE = re.compile(r"[^0-9a-z一-鿿]+")


def _text(value, cap: int = 2000) -> str:
    return str(value or "").strip()[:cap]


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    for old, new in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                     ("—", "-"), ("–", "-")):
        text = text.replace(old, new)
    return " ".join(text.split())


def _loose(text: str) -> str:
    """去掉标点与空白，只比内容顺序；防止句末标点差异误杀真引用。"""
    return _LOOSE.sub("", _normalized(text))


def quote_in_text(quote: str, text: str) -> bool:
    needle = _normalized(quote)
    if not needle:
        return False
    haystack = _normalized(text)
    if needle in haystack:
        return True
    loose_needle = _loose(quote)
    if len(loose_needle) < 4:
        return False
    return loose_needle in _loose(text)


def _severity(value) -> str:
    raw = str(value or "").strip()
    return raw if raw in rubric.SEVERITIES else "一般"


def filter_errors(raw, text: str, limit: int = MAX_ERRORS) -> tuple[list[dict], int]:
    """逐条核对 quote；伪造或过短的引用直接丢弃。"""
    rows: list[dict] = []
    dropped = 0
    seen: set[tuple[str, str]] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        quote = _text(item.get("quote"), 400)
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


def _card(kind: str, pack: dict, row: dict, index: int) -> dict:
    digest = hashlib.sha1(
        f"{row['quote']}\n{row['fix']}".encode("utf-8")).hexdigest()[:10]
    return {
        "source": kind,
        "source_id": f"{pack.get('id')}:{index}:{digest}",
        "question": f"改错：{row['quote']}",
        "answer": row["fix"],
        "my_answer": row["quote"],
        "tags": f"{row['type']} 写作" if kind == "writing" else f"{row['type']} 翻译",
        "note": row["why"],
        "auto": True,
    }


def _cards(kind: str, pack: dict, errors: list[dict]) -> list[dict]:
    rows = []
    for index, row in enumerate(errors, start=1):
        if row["type"] in NON_CARD_TYPES:
            continue
        if row["severity"] in CARD_SEVERITIES:
            rows.append(_card(kind, pack, row, index))
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
        "cards": _cards("writing", pack, errors),
        "term_cards": [],
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


def _alignment(raw, text: str, segment_count: int) -> list[dict]:
    """逐句对照：模型给段落序号 + 学生译文片段；片段必须能在原文找到。"""
    rows: list[dict] = []
    seen: set[int] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            segment = int(item.get("segment"))
        except (TypeError, ValueError):
            continue
        quote = _text(item.get("quote"), 400)
        if not 1 <= segment <= segment_count or segment in seen:
            continue
        if not quote_in_text(quote, text):
            continue
        seen.add(segment)
        rows.append({"segment": segment, "quote": quote})
    rows.sort(key=lambda row: row["segment"])
    return rows


def _term_cards(errors: list[dict]) -> list[dict]:
    rows = []
    for index, row in enumerate(errors, start=1):
        if "术语" not in row["type"]:
            continue
        rows.append({
            "front": row["quote"],
            "back": row["fix"],
            "tags": "术语 翻译",
            "note": row["why"],
            "auto": True,
        })
    return rows


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
        "alignment": _alignment(obj.get("alignment"), text,
                                len(pack.get("segments") or [])),
        "errors": errors,
        "errors_dropped": dropped,
        "priorities": _priorities(obj.get("priorities")),
        "rewrite_task": _text(obj.get("rewrite_task"), 600),
        "template": hard.get("template") or rubric.template_check(text),
        "hard_rules": hard,
        "cards": _cards("translation", pack, errors),
        "term_cards": _term_cards(errors),
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
    cards = [{
        "source": "translation",
        "source_id": f"{item.get('id')}:{index}:"
                     + hashlib.sha1(
                         f"{row['quote']}\n{row['fix']}".encode("utf-8")
                     ).hexdigest()[:10],
        "question": f"改译：{row['quote']}",
        "answer": row["fix"],
        "my_answer": row["quote"],
        "tags": f"{row['type']} 翻译",
        "note": row["why"],
        "auto": True,
    } for index, row in enumerate(must_fix, start=1)]
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
        "minimal_fix": _text(obj.get("minimal_fix"), 800),
        "idiomatic": _text(obj.get("idiomatic"), 800),
        "cards": cards,
        "term_cards": [],
    }


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
