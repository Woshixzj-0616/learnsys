"""把没有整句卡的翻译改错补成整句卡。

背景：2026-11-11 生词本口径收紧后，归档了 19 条多词改错；其中 5 条
（national rejuvenation / sit around / video calls / pay New Year greetings to /
peace and safety）所在的句子当时只属一般错误，没有进整句复习卡。
本工具从原始批改记录里按句重建整句卡：
- 原文找最早一次已批改且包含目标错误的提交；
- 把该句在 `band_json.errors` 里的全部错误放进背面；
- `t25` 的 national rejuvenation 是补录项，额外加一条改错说明。

默认只读；`--apply` 才写库。整句卡按句子哈希去重，已有卡只刷新内容，
保留复习进度。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.train import review as train_review  # noqa: E402

TARGETS = [
    {"prompt_id": "t01", "quote": "sit arround"},
    {"prompt_id": "t01", "quote": "happiness and fitness"},
    {"prompt_id": "t01", "quote": "call for"},
    {
        "prompt_id": "t25",
        "quote": "rejuvenation of China",
        "extra": {
            "type": "术语",
            "severity": "一般",
            "quote": "the rejuvenation of China",
            "fix": "national rejuvenation",
            "why": "“民族复兴”是 national rejuvenation；the Chinese Dream of national rejuvenation 是固定表达。",
            "gloss": "民族复兴",
        },
    },
]


def _submission(conn, prompt_id: str, quote: str):
    rows = conn.execute(
        "SELECT id, text, band_json FROM train_submissions "
        "WHERE kind='translation' AND prompt_id=? AND status='reviewed' "
        "AND text LIKE ? ORDER BY id ASC",
        (prompt_id, f"%{quote}%")).fetchall()
    return rows[0] if rows else None


def _errors(raw: str) -> list[dict]:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return []
    errors = data.get("errors") if isinstance(data, dict) else []
    return [row for row in errors or [] if isinstance(row, dict)]


def build(conn, target: dict) -> dict:
    prompt_id = target["prompt_id"]
    quote = target["quote"]
    sub = _submission(conn, prompt_id, quote)
    if sub is None:
        return {"target": target, "error": "没找到包含该错误的已批改提交"}
    text = str(sub[1] or "")
    errors = _errors(sub[2])
    if target.get("extra"):
        errors.append(target["extra"])
    sentence = train_review.sentence_around(text, quote)
    rows = [row for row in errors
            if train_review.sentence_around(text, str(row.get("quote") or ""))
            == sentence]
    if not sentence or not rows:
        return {"target": target, "error": "没找到可放进整句卡的错误"}
    card = train_review.translation_sentence_card(
        f"translation:{prompt_id}", sentence, rows)
    old = conn.execute(
        "SELECT id FROM wrong_items WHERE source=? AND source_id=?",
        (card["source"], card["source_id"])).fetchone()
    return {
        "target": target,
        "submission": int(sub[0]),
        "sentence": sentence,
        "rows": rows,
        "card": card,
        "existing_id": int(old[0]) if old else 0,
    }


def apply(conn, report: dict) -> int:
    card = report["card"]
    item_id, created = store.add_wrong_item(
        conn, question=card["question"], answer=card["answer"],
        my_answer=card.get("my_answer", ""), tags=card.get("tags", ""),
        note=card.get("note", ""), source=card["source"],
        source_id=card["source_id"], auto=bool(card.get("auto", True)),
        update_if_exists=True)
    report["item_id"] = item_id
    report["created"] = created
    return item_id


def _write_audit(reports: list[dict]) -> pathlib.Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.DATA_ROOT / "日志" / f"整句补卡-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = []
    for report in reports:
        payload.append({
            "target": report["target"],
            "submission": report.get("submission"),
            "sentence": report.get("sentence"),
            "rows": report.get("rows"),
            "existing_id": report.get("existing_id"),
            "item_id": report.get("item_id"),
            "created": report.get("created"),
            "error": report.get("error"),
        })
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="翻译改错补整句卡")
    parser.add_argument("--apply", action="store_true",
                        help="写入整句卡；默认只读")
    args = parser.parse_args()

    conn = store.connect()
    try:
        reports = []
        for target in TARGETS:
            report = build(conn, target)
            reports.append(report)
            print("=" * 60)
            print(f"目标：{target['prompt_id']} · {target['quote']}")
            if report.get("error"):
                print("  跳过：", report["error"])
                continue
            print(f"  提交 #{report['submission']} · 已有卡：{report['existing_id'] or '无'}")
            print("  句子：", report["sentence"])
            for row in report["rows"]:
                print(f"    - {row.get('quote')} → {row.get('fix')}")
        if not args.apply:
            print("\n只读模式；确认后加 --apply 写入。")
            return 0
        for report in reports:
            if report.get("error"):
                continue
            apply(conn, report)
            print(f"已写入：{report['target']['quote']} → 卡 #{report['item_id']}"
                  f"（{'新建' if report.get('created') else '更新'}）")
        store.seed_review_states(conn)
        audit = _write_audit(reports)
        print(f"\n审计文件：{audit}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
