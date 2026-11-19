"""整篇翻译复习卡回填：正面学生英文句 → 题库中文原文。

历史卡是旧版按学生英文句建的，正面给的是错译；
这里用 `train_submissions.band_json.alignment` + `translation.json.segments`
找到对应中文意群，并把学生英文移到背面 `my_answer`。

只处理 `source_id` 形如 `translation:t01:<sha1>` 的整篇翻译卡；
`translation` 一句一译卡（`sentence:x…`）本来就是中文，不动。

默认只读；`--apply` 才写库，写前自动备份。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.train import content as train_content  # noqa: E402
from learnsys.train.translation_cards import _segment_for_quote  # noqa: E402

CJK = re.compile(r"[一-鿿]")
OLD_ID = re.compile(r"^translation:(t\d+):[0-9a-f]{10}$")


def _has_cjk(text: str) -> bool:
    return bool(CJK.search(str(text or "")))


def _submissions(conn, pack_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, text, band_json FROM train_submissions "
        "WHERE kind = 'translation' AND prompt_id = ? AND status = 'reviewed' "
        "ORDER BY id DESC", (pack_id,)).fetchall()
    result = []
    for row in rows:
        try:
            review = json.loads(row[2] or "{}")
        except ValueError:
            review = {}
        result.append({
            "id": int(row[0]), "text": row[1] or "",
            "alignment": review.get("alignment") or [] if isinstance(review, dict) else [],
        })
    return result


def _locate(card: dict, pack: dict, submissions: list[dict]):
    segments = pack.get("segments") or []
    best = None
    for submission in submissions:
        index, inferred = _segment_for_quote(
            card["question"], submission["text"], submission["alignment"], segments)
        if index is None:
            continue
        candidate = (not inferred, index, submission)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best


def collect(conn) -> dict:
    packs = {row.get("id"): row for row in train_content.translation_items()}
    rows = conn.execute(
        "SELECT id, question, my_answer, source_id, answer, note FROM wrong_items "
        "WHERE source = 'translation' AND mastered = 0 "
        "ORDER BY id").fetchall()
    plans, skipped = [], []
    for row in rows:
        card = {"id": int(row[0]), "question": row[1] or "",
                "my_answer": row[2] or "", "source_id": row[3] or "",
                "answer": row[4] or "", "note": row[5] or ""}
        match = OLD_ID.match(card["source_id"])
        if not match or _has_cjk(card["question"]):
            continue
        pack = packs.get(match.group(1))
        if pack is None:
            skipped.append((card, "题库里找不到这套题"))
            continue
        located = _locate(card, pack, _submissions(conn, match.group(1)))
        if located is None:
            skipped.append((card, "找不到对应中文段落"))
            continue
        _inferred, index, submission = located
        segment = (pack.get("segments") or [])[index - 1]
        student = _student_quote(submission, index) or card["question"]
        plans.append({
            "card": card, "pack_id": match.group(1), "segment": index,
            "question": str(segment.get("zh") or "").strip(),
            "my_answer": student,
            "source_id": f"translation:{match.group(1)}:seg{index}",
        })
    return {"plans": plans, "skipped": skipped}


def _student_quote(submission: dict, index: int) -> str:
    for row in submission.get("alignment") or []:
        try:
            segment = int(row.get("segment"))
        except (TypeError, ValueError):
            continue
        if segment == index:
            return str(row.get("quote") or "").strip()
    return ""


def apply(conn, report: dict) -> dict:
    updated = conflicts = 0
    for plan in report["plans"]:
        existing = conn.execute(
            "SELECT id FROM wrong_items WHERE source = 'translation' "
            "AND source_id = ? AND id <> ?",
            (plan["source_id"], plan["card"]["id"])).fetchone()
        if existing is not None:
            conflicts += 1
            continue
        if not plan["question"]:
            continue
        store.rewrite_wrong_item(
            conn, plan["card"]["id"], source_id=plan["source_id"],
            question=plan["question"], my_answer=plan["my_answer"])
        updated += 1
    return {"updated": updated, "conflicts": conflicts}


def render(report: dict, applied: dict | None = None) -> str:
    lines = ["整篇翻译卡正面回填（只读）" if applied is None
             else "整篇翻译卡正面回填（已执行）",
             f"可回填：{len(report['plans'])} 张",
             f"未定位/跳过：{len(report['skipped'])} 张"]
    for plan in report["plans"]:
        card = plan["card"]
        lines.append(f"  #{card['id']} {plan['pack_id']} seg{plan['segment']}："
                     f"{plan['question']}")
        lines.append(f"    背面保留学生英文：{plan['my_answer'][:90]}")
    for card, reason in report["skipped"]:
        lines.append(f"  #{card['id']} 跳过：{reason}（{card['question'][:60]}）")
    if applied is None:
        lines.append("预检：加 --apply 才会写库。")
    else:
        lines.append("执行结果：更新 {updated} 张，source_id 冲突 {conflicts} 张"
                     .format(**applied))
    return "\n".join(lines)


def _backup(db_path: pathlib.Path) -> pathlib.Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.name}.bak-{stamp}-翻译卡正面")
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="整篇翻译卡正面回填（只读默认）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args(argv)

    db_path = pathlib.Path(args.db)
    if args.apply:
        if not db_path.is_file():
            print(f"数据库不存在：{db_path}")
            return 1
        print(f"已备份：{_backup(db_path)}")
    conn = store.connect(db_path)
    try:
        report = collect(conn)
        applied = apply(conn, report) if args.apply else None
        print(render(report, applied))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
