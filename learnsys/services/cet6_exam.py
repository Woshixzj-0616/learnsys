"""六级真题自评：按段听完整真题，逐题自评对/错，算 A/B/C 分段正确率。

口径：
- 试卷里没有 A/B/C/D 选项，也没有标准答案，所以这里记的是**自评**；
- 题干和音频只从试卷 `data.js` 读，不复制进数据库；
- 自评不建错题卡：没有选项/答案，硬建会污染 FSRS，本轮只做测量。
"""
from __future__ import annotations

import collections
import datetime as dt
import re

from learnsys import config, store
from learnsys.services import cet6_paper

_MAX_LIMIT = 5
_SECTION_RE = re.compile(r"Section\s+([A-C])")


def _since(days: int = 3) -> str:
    day = dt.date.today() - dt.timedelta(days=max(1, int(days or 3)))
    return f"{day.isoformat()} 00:00:00"


def section_letter(section: str) -> str:
    match = _SECTION_RE.search(str(section or ""))
    return match.group(1) if match else "其他"


def _accuracy(correct: int, questions: int) -> float:
    return round(correct / questions, 4) if questions else 0.0


def _pack(row: dict, questions: list[dict], audio: dict) -> dict:
    return {
        "paper_id": row["paper_id"],
        "paper_title": row["paper_title"],
        "section": row["section"],
        "section_letter": section_letter(row["section"]),
        "item": row["item"],
        "sentences": row["sentences"],
        "audio_url": audio["content"],
        "questions_url": audio["questions"],
        "questions": questions,
        "attempts": row["attempts"],
    }


def queue(conn, limit: int = 1) -> dict:
    """今日真题：A/B 段优先，最近 3 天做过的排后，练得少的先上。

    没有音频目录（测试环境/未装模块）时放宽音频检查；
    题干为空或试卷读不出来的段直接跳过。
    """
    limit = max(1, min(int(limit or 1), _MAX_LIMIT))
    since = _since(3)
    has_library = (config.cet6_dir() / "试卷").is_dir()
    rows = store.exam_candidates(conn, since=since, limit=max(limit * 12, 30))

    fresh: list[dict] = []
    recent: list[dict] = []
    for row in rows:
        try:
            questions = cet6_paper.item_questions(
                row["paper_title"], row["section"], row["item"])
        except cet6_paper.PaperNotFound:
            continue
        if not questions:
            continue
        audio = cet6_paper.item_audio(
            row["paper_title"], row["section"], row["item"])
        if has_library and (not audio["content"] or not audio["questions"]):
            continue
        item = _pack(row, questions, audio)
        if row["last_ts"] and row["last_ts"] >= since:
            recent.append(item)
        else:
            fresh.append(item)
        if len(fresh) >= limit:
            break

    items = (fresh + recent)[:limit]
    return {"items": items, "count": len(items)}


def attempt(conn, payload: dict) -> dict:
    paper_id = str(payload.get("paper_id") or "")
    section = str(payload.get("section") or "")
    item_name = str(payload.get("item") or "")
    row = store.exam_item(conn, paper_id=paper_id, section=section, item=item_name)
    if row is None:
        raise LookupError("这一段还没同步到后台，先回精听工作台打开一次")

    paper_title = row["paper_title"]
    try:
        questions = cet6_paper.item_questions(paper_title, section, item_name)
    except cet6_paper.PaperNotFound as exc:
        raise LookupError("试卷里找不到这一段的题干") from exc
    if not questions:
        raise LookupError("这一段没有题干，换一段或用逐句听写")

    valid = {int(q["number"]) for q in questions}
    raw_wrong = payload.get("wrong") or []
    if not isinstance(raw_wrong, (list, tuple)):
        raise ValueError("wrong 必须是题号列表")
    wrong: list[int] = []
    for value in raw_wrong:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"题号不是整数：{value}") from exc
        if number not in valid:
            raise ValueError(f"这一段没有第 {number} 题")
        if number not in wrong:
            wrong.append(number)
    wrong.sort()

    correct = len(valid) - len(wrong)
    duration = max(0, min(int(payload.get("duration_s") or 0), 3600))
    attempt_id = store.add_exam_attempt(
        conn, paper_id=paper_id, paper_title=paper_title, section=section,
        item=item_name, question_count=len(valid), correct_count=correct,
        wrong=wrong, duration_s=duration)

    transcript = [sent["en"] for sent in store.cet6_progress_item(
        conn, paper_id=paper_id, section=section, item=item_name)
        if sent.get("en")]
    return {
        "attempt_id": attempt_id,
        "paper_title": paper_title,
        "section": section,
        "section_letter": section_letter(section),
        "item": item_name,
        "question_count": len(valid),
        "correct_count": correct,
        "wrong": wrong,
        "self_accuracy": _accuracy(correct, len(valid)),
        "questions": questions,
        "transcript": transcript,
    }


def _bucket() -> dict:
    return {"attempts": 0, "questions": 0, "correct": 0}


def _finish(bucket: dict) -> dict:
    return {
        "attempts": bucket["attempts"],
        "questions": bucket["questions"],
        "correct": bucket["correct"],
        "self_accuracy": _accuracy(bucket["correct"], bucket["questions"]),
    }


def stats(conn, days: int = 30) -> dict:
    days = max(7, min(int(days or 30), 365))
    since = _since(days - 1)
    rows = store.exam_attempts(conn, since=since)

    sections: dict[str, dict] = collections.defaultdict(_bucket)
    papers: dict[str, dict] = collections.defaultdict(_bucket)
    daily: dict[str, dict] = collections.defaultdict(_bucket)
    items_seen: set[tuple] = set()
    total = _bucket()

    for row in rows:
        questions = int(row["question_count"] or 0)
        correct = int(row["correct_count"] or 0)
        letter = section_letter(row["section"])
        paper = row["paper_title"] or "未知试卷"
        day = str(row.get("ts") or "")[:10]
        items_seen.add((row["paper_id"], row["section"], row["item"]))
        for bucket in (total, sections[letter], papers[paper], daily[day]):
            bucket["attempts"] += 1
            bucket["questions"] += questions
            bucket["correct"] += correct

    recent = [{
        "ts": row["ts"],
        "paper_title": row["paper_title"],
        "section": row["section"],
        "section_letter": section_letter(row["section"]),
        "item": row["item"],
        "question_count": int(row["question_count"] or 0),
        "correct_count": int(row["correct_count"] or 0),
        "wrong": row["wrong"],
        "self_accuracy": _accuracy(int(row["correct_count"] or 0),
                                  int(row["question_count"] or 0)),
    } for row in rows][-5:][::-1]

    return {
        "range": {"days": days, "since": since[:10]},
        "total_attempts": len(rows),
        "items": len(items_seen),
        "questions": total["questions"],
        "correct": total["correct"],
        "self_accuracy": _accuracy(total["correct"], total["questions"]),
        "by_section": {key: _finish(value)
                       for key, value in sorted(sections.items())},
        "by_paper": [{"paper_title": key, **_finish(value)}
                     for key, value in sorted(
                         papers.items(), key=lambda kv: -kv[1]["attempts"])][:10],
        "daily": [{"date": day, **_finish(daily[day])}
                  for day in sorted(daily)][-14:],
        "recent": recent,
    }
