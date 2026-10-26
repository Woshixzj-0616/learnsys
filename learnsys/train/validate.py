"""内容包结构校验：`tools/check_train_content.py` 与测试共用这一份规则。"""
from __future__ import annotations

import pathlib
import re

from . import content, rubric

WRITING_COUNT = 12
TRANSLATION_COUNT = 12
MIN_DERIVED_SENTENCES = 70
MIN_EXTRA_SENTENCES = 60
_ID = re.compile(r"^(w|t)\d{2}$")
_XID = re.compile(r"^x\d{3}$")
_IPID = re.compile(r"^ip\d+$")


def _rows(value, name: str, low: int, high: int | None,
          errors: list[str], where: str) -> bool:
    if not isinstance(value, list):
        errors.append(f"{where}：{name} 必须是数组")
        return False
    if len(value) < low or (high is not None and len(value) > high):
        span = f"{low}" if high == low else f"{low}–{high}" if high else f"≥{low}"
        errors.append(f"{where}：{name} 需要 {span} 条，实际 {len(value)}")
        return False
    return True


def _texts(value, name: str, low: int, high: int | None,
           errors: list[str], where: str) -> bool:
    if not _rows(value, name, low, high, errors, where):
        return False
    for index, item in enumerate(value, start=1):
        if not str(item or "").strip():
            errors.append(f"{where}：{name} 第 {index} 条为空")
            return False
    return True


def _writing(item: dict, errors: list[str]) -> None:
    where = f"写作 {item.get('id') or '?'}"
    ident = str(item.get("id") or "")
    if not _ID.match(ident) or not ident.startswith("w"):
        errors.append(f"{where}：id 必须形如 w01")
    for key in ("title", "type", "prompt_en", "prompt_zh", "rewrite_task"):
        if not str(item.get(key) or "").strip():
            errors.append(f"{where}：缺 {key}")
    if len(str(item.get("prompt_en") or "")) < 80:
        errors.append(f"{where}：prompt_en 太短，至少 80 字符")
    words = item.get("target_words")
    if not (isinstance(words, list) and len(words) == 2
            and all(isinstance(x, int) for x in words) and words[0] < words[1]):
        errors.append(f"{where}：target_words 必须是 [下限, 上限] 两个整数")
    _texts(item.get("angle_points"), "angle_points", 3, 4, errors, where)
    _texts(item.get("stances"), "stances", 2, 3, errors, where)
    _texts(item.get("arguments"), "arguments", 4, 6, errors, where)
    _texts(item.get("collocations"), "collocations", 8, 12, errors, where)
    _texts(item.get("patterns"), "patterns", 5, 5, errors, where)
    _texts(item.get("pitfalls"), "pitfalls", 3, 8, errors, where)
    essay = item.get("model_essay")
    if not isinstance(essay, dict):
        errors.append(f"{where}：缺 model_essay")
    else:
        text = str(essay.get("text") or "")
        count = rubric.word_count(text)
        if not 150 <= count <= 200:
            errors.append(f"{where}：范文 {count} 词，需要 150–200")
        if rubric.normalize_band(essay.get("band")) not in (13, 14, 15):
            errors.append(f"{where}：范文档位需要 13–15")
        notes = essay.get("notes")
        if not isinstance(notes, list) or not notes:
            errors.append(f"{where}：范文缺逐段批注 notes")
        else:
            for row in notes:
                if not isinstance(row, dict) or not str(row.get("note") or "").strip():
                    errors.append(f"{where}：notes 有空项")
                    break
    upgrades = item.get("upgrades")
    if _rows(upgrades, "upgrades", 5, 5, errors, where):
        for index, row in enumerate(upgrades, start=1):
            if not isinstance(row, dict) or not all(
                    str(row.get(key) or "").strip()
                    for key in ("low", "high", "why")):
                errors.append(f"{where}：upgrades 第 {index} 条缺 low/high/why")


def _translation(item: dict, errors: list[str]) -> None:
    where = f"翻译 {item.get('id') or '?'}"
    ident = str(item.get("id") or "")
    if not _ID.match(ident) or not ident.startswith("t"):
        errors.append(f"{where}：id 必须形如 t01")
    for key in ("title", "theme", "source_zh", "reference"):
        if not str(item.get(key) or "").strip():
            errors.append(f"{where}：缺 {key}")
    chars = rubric.cjk_count(str(item.get("source_zh") or ""))
    low, high = rubric.TRANSLATION_SOURCE_CHARS
    if not low <= chars <= high:
        errors.append(f"{where}：原文 {chars} 个汉字，需要 {low}–{high}")
    try:
        difficulty = int(item.get("difficulty") or 0)
    except (TypeError, ValueError):
        difficulty = 0
    if not 1 <= difficulty <= 5:
        errors.append(f"{where}：difficulty 需要 1–5")
    points = item.get("info_points")
    point_ids: set[str] = set()
    if _rows(points, "info_points", 8, 12, errors, where):
        for row in points:
            pid = str((row or {}).get("id") or "")
            if not _IPID.match(pid):
                errors.append(f"{where}：信息点 id 非法：{pid or '空'}")
            elif pid in point_ids:
                errors.append(f"{where}：信息点 id 重复：{pid}")
            point_ids.add(pid)
            if not str((row or {}).get("zh") or "").strip():
                errors.append(f"{where}：信息点 {pid} 缺中文")
    segments = item.get("segments")
    covered: set[str] = set()
    if _rows(segments, "segments", 6, 8, errors, where):
        joined = ""
        for index, seg in enumerate(segments, start=1):
            seg = seg if isinstance(seg, dict) else {}
            zh = str(seg.get("zh") or "").strip()
            joined += zh
            if not zh:
                errors.append(f"{where}：第 {index} 段缺 zh")
            if not str(seg.get("reference") or "").strip():
                errors.append(f"{where}：第 {index} 段缺 reference")
            if not str(seg.get("skeleton") or "").strip():
                errors.append(f"{where}：第 {index} 段缺 skeleton")
            if seg.get("skill") not in content.SKILLS:
                errors.append(f"{where}：第 {index} 段 skill 非法")
            _texts(seg.get("keywords"), f"第 {index} 段 keywords", 1, 6,
                   errors, where)
            ids = seg.get("info_points")
            if not isinstance(ids, list) or not ids:
                errors.append(f"{where}：第 {index} 段缺 info_points")
            else:
                for pid in ids:
                    if pid not in point_ids:
                        errors.append(f"{where}：第 {index} 段引用了不存在的信息点 {pid}")
                    else:
                        covered.add(str(pid))
        source = re.sub(r"\s+", "", str(item.get("source_zh") or ""))
        if joined != source:
            errors.append(f"{where}：segments 拼起来与 source_zh 不一致")
    missing = point_ids - covered
    if missing:
        errors.append(f"{where}：信息点没有被任何段落覆盖：{'、'.join(sorted(missing))}")
    terms = item.get("terms")
    if _rows(terms, "terms", 8, 12, errors, where):
        for index, row in enumerate(terms, start=1):
            if not isinstance(row, dict) or not all(
                    str(row.get(key) or "").strip() for key in ("zh", "en")):
                errors.append(f"{where}：terms 第 {index} 条缺 zh/en")
    _texts(item.get("traps"), "traps", 5, 8, errors, where)
    _texts(item.get("typical_errors"), "typical_errors", 3, 6, errors, where)
    segments_len = len(segments) if isinstance(segments, list) else 0
    variants = item.get("variants")
    if _rows(variants, "variants", 1, 3, errors, where):
        for row in variants:
            try:
                seg_no = int((row or {}).get("segment"))
            except (TypeError, ValueError):
                seg_no = 0
            if not 1 <= seg_no <= segments_len:
                errors.append(f"{where}：variants 的 segment 越界")
            _texts((row or {}).get("options"), "variants.options", 1, 3,
                   errors, where)
    count = rubric.word_count(str(item.get("reference") or ""))
    if not 100 <= count <= 180:
        errors.append(f"{where}：参考译文 {count} 词，需要 100–180")


def _extra(item: dict, errors: list[str]) -> None:
    where = f"专项句 {item.get('id') or '?'}"
    if not _XID.match(str(item.get("id") or "")):
        errors.append(f"{where}：id 必须形如 x001")
    if item.get("skill") not in content.SKILLS:
        errors.append(f"{where}：skill 非法")
    for key in ("zh", "reference", "skeleton"):
        if not str(item.get(key) or "").strip():
            errors.append(f"{where}：缺 {key}")
    _texts(item.get("keywords"), "keywords", 1, 6, errors, where)
    _texts(item.get("info_points"), "info_points", 1, 3, errors, where)
    if "variants" in item:
        _texts(item.get("variants"), "variants", 0, 3, errors, where)


def check_library(lib: dict | None = None,
                  dir_path: pathlib.Path | str | None = None) -> list[str]:
    lib = lib or content.library(dir_path)
    errors: list[str] = []
    writing = lib["writing"]
    translation = lib["translation"]
    extra = lib["extra_sentences"]
    if len(writing) != WRITING_COUNT:
        errors.append(f"写作内容包需要 {WRITING_COUNT} 篇，实际 {len(writing)}")
    if len(translation) != TRANSLATION_COUNT:
        errors.append(f"翻译内容包需要 {TRANSLATION_COUNT} 篇，实际 {len(translation)}")
    seen: set[str] = set()
    for item in writing:
        _writing(item, errors)
        ident = str(item.get("id") or "")
        if ident in seen:
            errors.append(f"id 重复：{ident}")
        seen.add(ident)
    for item in translation:
        _translation(item, errors)
        ident = str(item.get("id") or "")
        if ident in seen:
            errors.append(f"id 重复：{ident}")
        seen.add(ident)
    if len(extra) < MIN_EXTRA_SENTENCES:
        errors.append(f"技能专项句需要 ≥{MIN_EXTRA_SENTENCES} 条，实际 {len(extra)}")
    for item in extra:
        _extra(item, errors)
        ident = str(item.get("id") or "")
        if ident in seen:
            errors.append(f"id 重复：{ident}")
        seen.add(ident)
    derived = content.derived_sentences(dir_path)
    if len(derived) < MIN_DERIVED_SENTENCES:
        errors.append(f"篇目派生句需要 ≥{MIN_DERIVED_SENTENCES} 条，实际 {len(derived)}")
    for item in derived:
        ident = str(item.get("id") or "")
        if ident in seen:
            errors.append(f"id 重复：{ident}")
        seen.add(ident)
        if not str(item.get("reference") or "").strip():
            errors.append(f"派生句 {ident} 缺 reference")
    return errors


def counts(lib: dict | None = None, dir_path=None) -> dict:
    lib = lib or content.library(dir_path)
    derived = content.derived_sentences(dir_path)
    return {
        "writing": len(lib["writing"]),
        "translation": len(lib["translation"]),
        "extra_sentences": len(lib["extra_sentences"]),
        "derived_sentences": len(derived),
        "sentences": len(lib["extra_sentences"]) + len(derived),
        "version": lib["version"],
    }
