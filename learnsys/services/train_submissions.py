"""写作/翻译提交的生命周期：草稿 → 提交 → 轮询 → 批改落库 → 错误卡。

模型调用在 `services/train_review.py`；这里只做业务编排与落库。
二稿新建一行，`parent_id` 指初稿；只有“严重”错误自动进错题本，术语错进生词本。
"""
from __future__ import annotations

import json

from learnsys import store
from learnsys.services import results, train_review
from learnsys.train import content, rubric

KINDS = ("writing", "translation")
MODES = ("timed", "practice", "rewrite")
MAX_TEXT = 8000


def _check_kind(kind: str) -> str:
    kind = str(kind or "").strip()
    if kind not in KINDS:
        raise ValueError("类型必须是 writing / translation")
    return kind


def _pack(kind: str, prompt_id: str) -> dict:
    item = content.pack(kind, prompt_id)
    if item is None:
        raise LookupError("没有这道题")
    return item


def _review_dict(row: dict) -> dict:
    try:
        data = json.loads(row.get("band_json") or "{}")
    except Exception:  # noqa: BLE001 - 坏 JSON 只影响详情，不影响列表
        return {}
    return data if isinstance(data, dict) else {}


def prompt_brief(item: dict, stats: dict) -> dict:
    base = {
        "id": item["id"], "kind": item["kind"], "title": item.get("title", ""),
        "minutes": item.get("minutes", 30), "done": stats.get("done", 0),
        "last_band": stats.get("last_band"),
    }
    if item["kind"] == "writing":
        base.update({"type": item.get("type", ""),
                     "target_words": item.get("target_words", [150, 200])})
    else:
        base.update({"theme": item.get("theme", ""),
                     "difficulty": item.get("difficulty", 1)})
    return base


def list_prompts(conn, kind: str) -> dict:
    kind = _check_kind(kind)
    stats = store.latest_train_by_prompt(conn, kind)
    items = content.writing_items() if kind == "writing" else content.translation_items()
    return {"kind": kind,
            "items": [prompt_brief(item, stats.get(item["id"], {}))
                      for item in items]}


def prompt_detail(kind: str, prompt_id: str) -> dict:
    kind = _check_kind(kind)
    item = dict(_pack(kind, prompt_id))
    # 范文与升级对照只在提交后（复盘）展示，不提前下发。
    item.pop("model_essay", None)
    item.pop("upgrades", None)
    if kind == "translation":
        # 限时/练习都不提前给参考译文、逐句切分和术语英文。
        return {
            "id": item["id"], "kind": "translation",
            "title": item.get("title", ""), "theme": item.get("theme", ""),
            "difficulty": item.get("difficulty", 1),
            "minutes": item.get("minutes", 30),
            "source_zh": item.get("source_zh", ""),
        }
    return item


def list_terms(pack_id: str = "") -> dict:
    """术语卡：中文 → 英文；按 zh+en 去重，跨篇共用一张卡。"""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in content.translation_items():
        if pack_id and item["id"] != pack_id:
            continue
        for term in item.get("terms") or []:
            zh = str(term.get("zh") or "").strip()
            en = str(term.get("en") or "").strip()
            if not zh or not en or (zh, en) in seen:
                continue
            seen.add((zh, en))
            rows.append({
                "zh": zh, "en": en, "note": term.get("note", ""),
                "pack_id": item["id"], "pack_title": item.get("title", ""),
            })
    return {"items": rows, "count": len(rows)}


def create_submission(conn, *, kind: str, prompt_id: str,
                      mode: str = "practice", parent_id: int = 0) -> dict:
    kind = _check_kind(kind)
    item = _pack(kind, prompt_id)
    mode = str(mode or "practice")
    if mode not in MODES:
        raise ValueError("模式必须是 timed / practice / rewrite")
    initial_text = ""
    initial_words = 0
    if parent_id:
        parent = store.get_submission(conn, int(parent_id))
        if parent is None:
            raise LookupError("初稿不存在")
        if parent["kind"] != kind or parent["prompt_id"] != prompt_id:
            raise ValueError("二稿必须与初稿是同一道题")
        mode = "rewrite"
        # 二稿预填必须落库：只靠前端预填，用户直接离开就会变成空草稿。
        initial_text = parent.get("text") or ""
        initial_words = int(parent.get("word_count") or 0)
    sub_id = store.create_submission(
        conn, kind=kind, prompt_id=prompt_id,
        content_version=item.get("content_version", ""), mode=mode,
        parent_id=int(parent_id or 0), text=initial_text,
        word_count=initial_words)
    return detail(conn, sub_id)


def patch_submission(conn, submission_id: int, *, text: str | None = None,
                     duration_s: int | None = None,
                     flags: dict | None = None) -> dict:
    row = store.get_submission(conn, submission_id)
    if row is None:
        raise LookupError("这次提交不存在")
    if row["status"] not in ("draft", "failed"):
        raise ValueError("已经提交，正文不能再改；要改请开二稿")
    changes: dict = {}
    if text is not None:
        value = str(text)[:MAX_TEXT]
        changes["text"] = value
        changes["word_count"] = rubric.word_count(value)
    if duration_s is not None:
        changes["duration_s"] = max(0, int(duration_s))
    if flags is not None:
        merged = dict(row.get("flags") or {})
        for key in ("pasted_chars", "left_seconds"):
            try:
                merged[key] = max(int(merged.get(key) or 0), int(flags.get(key) or 0))
            except (TypeError, ValueError):
                continue
        changes["flags_json"] = json.dumps(merged, ensure_ascii=False)
    if changes:
        store.update_submission(conn, submission_id, **changes)
    return detail(conn, submission_id)


def _merge_flags(row: dict, flags: dict | None) -> dict:
    merged = dict(row.get("flags") or {})
    flags = flags if isinstance(flags, dict) else {}
    for key in ("pasted_chars", "left_seconds"):
        try:
            merged[key] = max(int(merged.get(key) or 0), int(flags.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return merged


def _start_review(conn, row: dict, flags: dict, *, force: bool) -> dict:
    sub_id = int(row["id"])
    if len(str(row.get("text") or "").strip()) < 10:
        raise ValueError("作文太短，至少写 10 个字符再提交")
    merged = _merge_flags(row, flags)
    store.update_submission(conn, sub_id, status="reviewing",
                            flags_json=json.dumps(merged, ensure_ascii=False))
    started = train_review.submit(
        {"kind": row["kind"], "prompt_id": row["prompt_id"],
         "text": row["text"], "flags": merged},
        target_id=f"train:{sub_id}", force=force)
    store.update_submission(conn, sub_id, result_id=int(started.get("id") or 0))
    if started.get("status") == "done":
        _apply_result(conn, sub_id, int(started["id"]))
    return detail(conn, sub_id)


def record_training_event(conn, row: dict) -> None:
    """一次新提交 = 一条训练事件（XP/连续天数/复盘共用）；重批不再记。"""
    kind = row.get("kind") if row.get("kind") in KINDS else "translation"
    pack = content.pack(kind, row.get("prompt_id")) or {}
    label = "写作" if kind == "writing" else "翻译"
    store.add_event(
        conn, "train", kind,
        title=f"{label} · {pack.get('title') or row.get('prompt_id') or ''}",
        meta={"kind": kind, "prompt_id": row.get("prompt_id", ""),
              "mode": row.get("mode", "")},
        ref_id=int(row.get("id") or 0))


def submit_submission(conn, submission_id: int, *,
                      flags: dict | None = None) -> dict:
    row = store.get_submission(conn, submission_id)
    if row is None:
        raise LookupError("这次提交不存在")
    if row["status"] == "reviewing":
        return detail(conn, submission_id)
    if row["status"] == "reviewed":
        raise ValueError("已经批改过；要重批请点「重新批改」")
    first_submit = row["status"] == "draft"
    out = _start_review(conn, row, flags or {}, force=False)
    if first_submit:
        record_training_event(conn, row)
    return out


def review_submission(conn, submission_id: int, *,
                      flags: dict | None = None) -> dict:
    row = store.get_submission(conn, submission_id)
    if row is None:
        raise LookupError("这次提交不存在")
    if row["status"] in ("draft", "reviewing"):
        raise ValueError("还没提交或正在批改，不能重新批改")
    return _start_review(conn, row, flags or {}, force=True)


def _store_cards(conn, row: dict, review: dict) -> dict:
    source = "writing" if row["kind"] == "writing" else "translation"
    added = 0
    for card in review.get("cards") or []:
        question = str(card.get("question") or "").strip()
        if not question:
            continue
        _, created = store.add_wrong_item(
            conn, question=question, answer=card.get("answer", ""),
            my_answer=card.get("my_answer", ""), tags=card.get("tags", ""),
            note=card.get("note", ""), source=source,
            source_id=f"{source}:{card.get('source_id') or store.wrong_fingerprint(question)}",
            auto=bool(card.get("auto", True)))
        added += 1 if created else 0
    terms = 0
    for card in review.get("term_cards") or []:
        word = str(card.get("front") or "").strip()
        if not word:
            continue
        _, created = store.add_vocab(
            conn, word=word, meaning=card.get("back", ""),
            context=card.get("note", ""), paper_id=row["prompt_id"],
            source="translation")
        terms += 1 if created else 0
    return {"wrong_added": added, "terms_added": terms}


def _apply_result(conn, submission_id: int, result_id: int) -> bool:
    result = results.get(conn, result_id)
    if result is None or result["status"] != "done":
        return False
    try:
        review = json.loads(result.get("content_json") or "{}")
    except Exception:  # noqa: BLE001
        review = {}
    if not isinstance(review, dict) or not review:
        store.update_submission(conn, submission_id, status="failed",
                                band_json=json.dumps(
                                    {"error": "批改结果读不出来"}, ensure_ascii=False))
        return False
    band = review.get("band")
    store.set_submission_review(conn, submission_id, band=band,
                                review=review, result_id=result_id)
    _store_cards(conn, store.get_submission(conn, submission_id) or {}, review)
    return True


def refresh(conn, submission_id: int) -> dict | None:
    """轮询入口：任务完成就落库；失败写 failed，页面不再空转。"""
    row = store.get_submission(conn, submission_id)
    if row is None or row["status"] != "reviewing":
        return row
    result_id = int(row.get("result_id") or 0)
    if not result_id:
        return row
    result = results.get(conn, result_id)
    if result is None:
        return row
    if result["status"] == "done":
        _apply_result(conn, submission_id, result_id)
    elif result["status"] in ("error", "canceled"):
        message = result.get("error") or "批改失败，请重试"
        store.update_submission(
            conn, submission_id, status="failed",
            band_json=json.dumps({"error": message}, ensure_ascii=False))
    return store.get_submission(conn, submission_id)


def detail(conn, submission_id: int) -> dict:
    row = refresh(conn, submission_id)
    if row is None:
        raise LookupError("这次提交不存在")
    pack = content.pack(row["kind"], row["prompt_id"]) or {}
    review = _review_dict(row)
    out = dict(row)
    out.update({
        "title": pack.get("title", ""),
        "prompt_en": pack.get("prompt_en", ""),
        "prompt_zh": pack.get("prompt_zh", ""),
        "type": pack.get("type", ""),
        "target_words": pack.get("target_words", []),
        "review": review,
        "error": review.get("error", "") if row["status"] == "failed" else "",
    })
    if row["status"] == "reviewed":
        out["model_essay"] = pack.get("model_essay")
        out["upgrades"] = pack.get("upgrades")
        out["angles"] = pack.get("angle_points")
        if row["kind"] == "translation":
            # 复盘才给参考译文与逐句切分，做题前 prompt_detail 已剥掉。
            out["segments"] = pack.get("segments") or []
            out["reference"] = pack.get("reference") or ""
            out["terms"] = pack.get("terms") or []
            out["info_point_table"] = pack.get("info_points") or []
    if row.get("parent_id"):
        parent = store.get_submission(conn, int(row["parent_id"]))
        if parent:
            parent_review = _review_dict(parent)
            out["parent"] = {
                "id": parent["id"], "band": parent["band"],
                "text": parent["text"], "word_count": parent["word_count"],
                "priorities": parent_review.get("priorities") or [],
            }
    return out


def history(conn, kind: str, *, limit: int = 50, offset: int = 0) -> dict:
    kind = _check_kind(kind)
    data = store.list_submissions(conn, kind=kind, exclude_mode="sentence",
                                  limit=limit, offset=offset)
    items = []
    for row in data["items"]:
        pack = content.pack(kind, row["prompt_id"]) or {}
        items.append({
            "id": row["id"], "prompt_id": row["prompt_id"],
            "title": pack.get("title", ""), "mode": row["mode"],
            "status": row["status"], "band": row["band"],
            "word_count": row["word_count"], "error_count": row["error_count"],
            "serious_count": row["serious_count"],
            "parent_id": row["parent_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "preview": str(row.get("text") or "")[:160],
        })
    return {"kind": kind, "items": items, "count": data["count"]}


def set_external_score(conn, submission_id: int, score: float | None) -> dict:
    row = store.get_submission(conn, submission_id)
    if row is None:
        raise LookupError("这次提交不存在")
    if score is not None:
        score = float(score)
        if not 0 <= score <= 15:
            raise ValueError("外部分数按 0–15 档录入")
    store.update_submission(conn, submission_id, external_score=score)
    return detail(conn, submission_id)
