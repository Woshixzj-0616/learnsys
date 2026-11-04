"""生词本去重报告：归档旧术语卡、中文词头转英文词头。

背景：旧版批改把「学生写错 → 正确英文」的术语卡原样写进生词本，
产生 `spring paper → spring couplets` 这种英文-英文条目；翻译页的
「加入生词本」又把中文词头存进库，和每日积累的英文词头同概念各存一份。

规则：
- 英文词头 + 英文释义 → 视为旧术语卡，归档（不删除，可恢复）；
- 中文词头 + 英文释义 → 原地转成英文词头 + 中文释义，保留 id 与复习状态；
- 目标词头已存在时，把空字段补到目标上，再归档旧行。

默认只读；`--apply` 才写库。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402

CJK = re.compile(r"[一-鿿]")


def _has_cjk(text: str) -> bool:
    return bool(CJK.search(str(text or "")))


def collect(conn) -> dict:
    items = store.list_vocab(conn, limit=500)["items"]
    junk, swaps = [], []
    for item in items:
        word = str(item.get("word") or "")
        meaning = str(item.get("meaning") or "")
        new_word, new_meaning = store.normalize_pair(word, meaning)
        if (not _has_cjk(word) and not _has_cjk(meaning)
                and item.get("source") == "translation"):
            junk.append(item)
        elif (new_word, new_meaning) != (word, meaning):
            swaps.append({
                "item": item,
                "word": new_word,
                "meaning": new_meaning,
                "normalized": " ".join(new_word.lower().split()),
            })
    return {"items": items, "junk": junk, "swaps": swaps}


def apply(conn, report: dict) -> dict:
    archived = reoriented = merged = 0
    for item in report["junk"]:
        store.update_vocab(conn, item["id"], status="archived")
        archived += 1

    # 归档后重新取活动行，按新词头建立索引。
    active = store.list_vocab(conn, limit=500)["items"]
    by_norm = {row["normalized"]: row for row in active}
    for row in report["swaps"]:
        old = row["item"]
        target = by_norm.get(row["normalized"])
        if target is not None and target["id"] != old["id"]:
            updates = {key: old.get(key) for key in ("meaning", "context", "phonetic")
                       if old.get(key) and not target.get(key)}
            if updates:
                target = store.update_vocab(conn, target["id"], **updates) or target
            old_state = store.get_review_state(conn, "vocab", old["id"])
            if old_state and store.get_review_state(conn, "vocab", target["id"]) is None:
                store.save_review_state(
                    conn, "vocab", target["id"],
                    state=old_state.get("state") or "new",
                    due=old_state.get("due") or "",
                    stability=old_state.get("stability") or 0,
                    difficulty=old_state.get("difficulty") or 0,
                    reps=old_state.get("reps") or 0,
                    lapses=old_state.get("lapses") or 0,
                    last_review=old_state.get("last_review") or "",
                    scheduled_days=old_state.get("scheduled_days") or 0,
                    elapsed_days=old_state.get("elapsed_days") or 0)
            store.update_vocab(conn, old["id"], status="archived")
            merged += 1
        else:
            updated = store.reorient_vocab(
                conn, old["id"], word=row["word"], meaning=row["meaning"])
            if updated:
                by_norm[row["normalized"]] = updated
            reoriented += 1
    return {"archived": archived, "reoriented": reoriented, "merged": merged}


def render(report: dict, applied: dict | None = None) -> str:
    lines = ["生词本去重报告（只读）" if applied is None else "生词本去重报告（已执行）",
             f"活动条目：{len(report['items'])}",
             f"英文-英文（旧术语卡）：{len(report['junk'])} 条"]
    for item in report["junk"]:
        lines.append(f"  #{item['id']}  {item['word']} → {item['meaning']}"
                     f"  [{item.get('source') or ''}]")
    lines.append(f"中文词头待转英文：{len(report['swaps'])} 条")
    for row in report["swaps"]:
        item = row["item"]
        lines.append(f"  #{item['id']}  {item['word']} → {row['word']}"
                     f"  （释义：{row['meaning']}）")
    if applied is not None:
        lines.append("执行结果：归档 {archived} 条，原地转写 {reoriented} 条，"
                     "合并 {merged} 条".format(**applied))
    else:
        lines.append("预检：加 --apply 才会写库。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生词本去重报告（只读默认）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args(argv)
    conn = store.connect(pathlib.Path(args.db))
    try:
        report = collect(conn)
        applied = apply(conn, report) if args.apply else None
        print(render(report, applied))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
