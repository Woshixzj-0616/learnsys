"""一句一译：单句题库、同步审核、尝试落库、必改错误卡。

口径（施工单 §5.7）：
- 提交前不下发参考译文与可接受变体；
- 单句只跑 1 次模型，目标 2 秒；
- 只有 must_fix 自动进错题本；suggestions 只展示；
- 每次尝试都落 `train_submissions(mode=sentence)`，供统计与“已练”去重。
"""
from __future__ import annotations

import hashlib
import json

from learnsys import store
from learnsys.services import train_review
from learnsys.train import content, rubric

MAX_TEXT = 2000


def _version(item: dict) -> str:
    payload = f"{item.get('zh')}\n{item.get('reference')}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _public(item: dict) -> dict:
    """做题前可见字段：参考译文、变体一律不出现。"""
    return {
        "id": item.get("id"),
        "skill": item.get("skill", ""),
        "zh": item.get("zh", ""),
        "keywords": list(item.get("keywords") or []),
        "skeleton": item.get("skeleton", ""),
        "info_points": list(item.get("info_points") or []),
        "source_id": item.get("source_id", ""),
        "source_title": item.get("source_title", ""),
        "origin": item.get("origin", ""),
    }


def _attempted(conn) -> set[str]:
    try:
        return set(store.sentence_attempted(conn))
    except Exception:  # noqa: BLE001 - 统计失败不该挡住练习
        return set()


def list_sentences(conn, *, skill: str = "", limit: int = 30,
                   offset: int = 0) -> dict:
    rows = content.sentence_items()
    if skill:
        rows = [item for item in rows if item.get("skill") == skill]
    attempted = _attempted(conn)
    items = []
    for item in rows[offset:offset + max(1, min(200, int(limit)))]:
        row = _public(item)
        row["attempted"] = row["id"] in attempted
        items.append(row)
    skills = sorted({item.get("skill") for item in content.sentence_items() if item.get("skill")})
    return {"items": items, "count": len(rows), "attempted_count": len(attempted),
            "skills": skills}


def get_sentence(conn, sentence_id: str) -> dict:
    item = content.sentence(sentence_id)
    if item is None:
        raise LookupError("没有这道单句练习题")
    row = _public(item)
    row["attempted"] = sentence_id in _attempted(conn)
    return row


def _store_cards(conn, sentence_id: str, review: dict) -> int:
    added = 0
    for card in review.get("cards") or []:
        question = str(card.get("question") or "").strip()
        if not question:
            continue
        _, created = store.add_wrong_item(
            conn, question=question, answer=card.get("answer", ""),
            my_answer=card.get("my_answer", ""), tags=card.get("tags", ""),
            note=card.get("note", ""), source="translation",
            source_id=f"sentence:{sentence_id}:{card.get('source_id') or store.wrong_fingerprint(question)}",
            auto=True)
        added += 1 if created else 0
    return added


def review_sentence(conn, sentence_id: str, text: str,
                    flags: dict | None = None) -> dict:
    item = content.sentence(sentence_id)
    if item is None:
        raise LookupError("没有这道单句练习题")
    text = str(text or "").strip()[:MAX_TEXT]
    if len(text) < 1:
        raise ValueError("先写一句英文再提交")
    flags = flags if isinstance(flags, dict) else {}
    data = train_review.review_sync(
        {"kind": "sentence", "prompt_id": sentence_id, "text": text,
         "flags": flags}, samples=1)
    review = data["review"]
    review["content_version"] = review.get("content_version") or _version(item)
    must_fix = review.get("must_fix") or []
    sub_id = store.create_submission(
        conn, kind="translation", prompt_id=sentence_id,
        content_version=review["content_version"], mode="sentence",
        text=text, word_count=rubric.word_count(text), flags=flags)
    store.update_submission(
        conn, sub_id, status="reviewed",
        band_json=json.dumps(review, ensure_ascii=False),
        error_count=len(must_fix), serious_count=len(must_fix))
    cards_added = _store_cards(conn, sentence_id, review)
    store.add_event(
        conn, "train", "sentence",
        title=f"一句一译 · {item.get('skill') or '翻译'}",
        meta={"kind": "translation", "prompt_id": sentence_id,
              "mode": "sentence"},
        ref_id=sub_id)
    return {
        "review": review,
        "attempt_id": sub_id,
        "cards_added": cards_added,
        "model": data.get("model", ""),
        "ms": data.get("ms", 0),
    }
