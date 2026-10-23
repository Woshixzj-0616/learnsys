"""知识点与答题流水的业务层：归一、落库、统计、旧错题回填。"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import sqlite3

from learnsys import knowledge, store
from learnsys.services import bkt

_SOURCE_ID_RE = re.compile(r"^quiz:(\d+):([0-9a-f]{16})$")
_ANSWER_NOISE = re.compile(r"[\s，。！？；：、“”‘’（）【】《》〈〉「」『』…—～·,.;:!?'\"()\[\]]+")


def _answer_key(text: str) -> str:
    cleaned = _ANSWER_NOISE.sub("", str(text or "")).casefold()
    return hashlib.sha1((cleaned or str(text or "")).encode("utf-8")).hexdigest()[:16]


def _raw_points(points) -> str:
    if isinstance(points, str):
        return points
    if isinstance(points, (list, tuple, set)):
        return "、".join(str(x) for x in points if str(x or "").strip())
    return ""


def _start_day(days: int) -> str:
    days = max(0, int(days or 0))
    if not days:
        return ""
    return (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()


def add_attempt(conn: sqlite3.Connection, *, question: str, my_answer: str,
                correct: bool | None, conversation_id: int = 0, material_id: int = 0,
                question_no: int = 0, feedback: str = "", points=None) -> dict:
    """记录一次作答（含答对）；同会话同题同答重复提交只算一次。"""
    question = str(question or "").strip()
    my_answer = str(my_answer or "").strip()
    if not question or not my_answer:
        raise ValueError("题目或作答为空，没有记录")

    names, source = knowledge.normalize_points(points)
    if len(names) > 3:
        names = names[:3]
        parse_ok = False
    else:
        parse_ok = bool(correct is not None and source == "model")
    points_source = source
    question_key = store.wrong_fingerprint(question)
    origin_key = (f"quiz:{int(conversation_id or 0)}:{question_key}:"
                  f"{_answer_key(my_answer)}")
    ts = store.now()
    correct_int = None if correct is None else (1 if correct else 0)
    attempt_id, created = store.add_knowledge_attempt(
        conn, ts=ts, day=ts[:10], conversation_id=conversation_id,
        material_id=material_id, question_no=question_no, question_key=question_key,
        question=question, my_answer=my_answer, correct=correct_int,
        feedback=feedback, source="quiz", points_source=points_source,
        points_raw=_raw_points(points), parse_ok=1 if parse_ok else 0,
        origin_key=origin_key, points=names)
    return {
        "ok": True, "id": attempt_id, "created": created,
        "correct": correct, "points": names, "points_source": points_source,
        "parse_ok": parse_ok,
    }


def attempt_stats(conn: sqlite3.Connection, days: int = 0) -> dict:
    start_day = _start_day(days)
    data = store.knowledge_stats(conn, start_day)

    # BKT：只认 ready_attempts 的顺序与口径；「其他」不建模。
    ready = store.ready_attempts(conn, start_day)
    modeled = {p["name"] for p in data["points"] if p["kind"] != "other"}
    observations = {name: [] for name in modeled}
    for attempt in ready:
        for name in attempt["points"]:
            if name in observations:
                observations[name].append(attempt["correct"])

    ready_points = []
    for point in data["points"]:
        if point["kind"] == "other":
            point["mastery"] = None
            point["mastery_attempts"] = 0
            point["mastery_ready"] = False
            point["mastery_level"] = "不建模"
            continue
        values = observations.get(point["name"], [])
        point["mastery_attempts"] = len(values)
        point["mastery_ready"] = len(values) >= bkt.MIN_SAMPLES
        point["mastery"] = (round(bkt.mastery(values), 4)
                            if point["mastery_ready"] else None)
        point["mastery_level"] = bkt.level(
            point["mastery"], len(values), modeled=True)
        if point["mastery_ready"]:
            ready_points.append(point)

    totals = data["totals"]
    totals["mastery_ready_points"] = len(ready_points)
    totals["average_mastery"] = (
        round(sum(p["mastery"] for p in ready_points) / len(ready_points), 4)
        if ready_points else None)
    weakest = (min(ready_points,
                   key=lambda p: (p["mastery"], -p["mastery_attempts"],
                                  p["sort"], p["id"]))
               if ready_points else None)
    totals["weakest"] = ({"id": weakest["id"], "name": weakest["name"],
                          "mastery": weakest["mastery"]} if weakest else None)

    since = store.knowledge_meta(conn, "knowledge_attempts_since")
    done_at = store.knowledge_meta(conn, "knowledge_backfilled_at")
    return {
        "days": max(0, int(days or 0)),
        "points": data["points"],
        "totals": totals,
        "bkt": bkt.params_meta(),
        "backfill": {"done": bool(done_at), "at": done_at, "since": since},
        "generated_at": store.now(),
    }


def point_attempts(conn: sqlite3.Connection, point_id: int, limit: int = 20,
                   offset: int = 0, days: int = 0) -> dict | None:
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    return store.knowledge_point_attempts(
        conn, point_id, limit=limit, offset=offset, start_day=_start_day(days))


def _source_parts(source_id: str, question: str) -> tuple[int, str]:
    match = _SOURCE_ID_RE.match(str(source_id or "").strip())
    if match:
        return int(match.group(1)), match.group(2)
    return 0, store.wrong_fingerprint(question)


def backfill_wrong_items(conn: sqlite3.Connection, *, dry_run: bool = False,
                         force: bool = False) -> dict:
    """把升级前的 quiz 错题补成历史答题；只展示，不计入 BKT-ready。"""
    since = store.knowledge_meta(conn, "knowledge_attempts_since")
    if not since:
        since = store.now()
        if not dry_run:
            store.set_knowledge_meta(conn, "knowledge_attempts_since", since)
    done_at = store.knowledge_meta(conn, "knowledge_backfilled_at")
    if done_at and not force:
        data = store.knowledge_stats(conn)
        return {"ok": True, "dry_run": bool(dry_run), "already_done": True,
                "before": since, "scanned": 0, "created": 0, "duplicate": 0,
                "live_skipped": 0, "points": {"tags": 0, "fallback": 0},
                "total_attempts": data["totals"]["attempts"]}

    candidates = store.backfill_candidates(conn, since)
    created = duplicate = live_skipped = 0
    point_counts = {"tags": 0, "fallback": 0}
    for item in candidates:
        conversation_id, question_key = _source_parts(
            item["source_id"], item["question"])
        if conversation_id and store.has_live_attempt(
                conn, conversation_id, question_key):
            live_skipped += 1
            continue
        origin_key = f"backfill:wrong:{item['id']}"
        if store.attempt_exists(conn, origin_key):
            duplicate += 1
            continue
        names, source = knowledge.normalize_points(item["tags"])
        points_source = "tags" if source == "model" else "fallback"
        point_counts["tags" if points_source == "tags" else "fallback"] += 1
        if dry_run:
            created += 1
            continue
        ts = item["ts"] or store.now()
        _, was_created = store.add_knowledge_attempt(
            conn, ts=ts, day=ts[:10], conversation_id=conversation_id,
            material_id=item["material_id"], question_no=0,
            question_key=question_key,
            question=(item["question"] or "").strip() or "（旧错题）",
            my_answer=item["my_answer"], correct=0, feedback=item["answer"],
            source="backfill", points_source=points_source,
            points_raw=item["tags"], parse_ok=0, origin_key=origin_key,
            points=names)
        if was_created:
            created += 1
        else:
            duplicate += 1

    if not dry_run:
        store.set_knowledge_meta(conn, "knowledge_backfilled_at", store.now())
    data = store.knowledge_stats(conn)
    return {"ok": True, "dry_run": bool(dry_run), "already_done": False,
            "before": since, "scanned": len(candidates), "created": created,
            "duplicate": duplicate, "live_skipped": live_skipped,
            "points": point_counts,
            "total_attempts": data["totals"]["attempts"]}
