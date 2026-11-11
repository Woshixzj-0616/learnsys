"""生词本口径审计：只留单词 / 术语 / 专有名词，多词改错归档。

背景：旧版回填把翻译句子里的普通搭配改错也写进了生词本，单词 tab 里
会看到 `stay up late to see the old year out` 这类整句表达。现在口径：
- 单个生词 → 保留；
- 题库术语表里的术语 → 保留；
- 明显大写的专有名词（如 `the Chinese Dream`）→ 保留；
- 其他多词改错 → 归档（不删除，可恢复），原句和改法仍在整句卡里。

默认只读；`--apply` 才归档。归档只改 `vocab_items.status`，不动复习日志。
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
from learnsys.train import content, lexical  # noqa: E402

SOURCES = ("translation", "sentence")


def _terms() -> list[dict]:
    rows: list[dict] = []
    for item in content.translation_items():
        for term in item.get("terms") or []:
            if isinstance(term, dict):
                rows.append(term)
    return rows


def classify(word: str, terms=None) -> str:
    words = lexical._clean(word).split()
    if len(words) <= 1:
        return "单词"
    if lexical.term_meaning(word, terms):
        return "术语"
    if lexical.is_proper_noun_shape(word):
        return "专有名词"
    return "多词改错"


def collect(conn) -> dict:
    terms = _terms()
    items: list[dict] = []
    for item in store.list_vocab(conn, limit=500)["items"]:
        if item.get("source") not in SOURCES:
            continue
        row = dict(item)
        row["scope"] = classify(str(item.get("word") or ""), terms)
        items.append(row)
    keep = [row for row in items if row["scope"] != "多词改错"]
    drop = [row for row in items if row["scope"] == "多词改错"]
    return {"items": items, "keep": keep, "drop": drop}


def apply(conn, report: dict) -> int:
    archived = 0
    for row in report["drop"]:
        store.update_vocab(conn, row["id"], status="archived")
        archived += 1
    return archived


def _write_audit(report: dict, archived: int) -> pathlib.Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.DATA_ROOT / "日志" / f"生词本口径-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "archived": archived,
        "drop": [
            {key: row.get(key) for key in
             ("id", "word", "meaning", "context", "source", "scope")}
            for row in report["drop"]
        ],
        "keep": [
            {key: row.get(key) for key in
             ("id", "word", "meaning", "source", "scope")}
            for row in report["keep"]
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="生词本口径审计")
    parser.add_argument("--apply", action="store_true",
                        help="归档多词改错；默认只读")
    args = parser.parse_args()

    conn = store.connect()
    try:
        report = collect(conn)
        print(f"活动生词（翻译 / 一句一译来源）：{len(report['items'])} 条")
        counts: dict[str, int] = {}
        for row in report["items"]:
            counts[row["scope"]] = counts.get(row["scope"], 0) + 1
        for scope in ("单词", "术语", "专有名词", "多词改错"):
            print(f"  {scope}：{counts.get(scope, 0)}")
        if report["drop"]:
            print("\n会归档的多词改错：")
            for row in report["drop"]:
                print(f"  #{row['id']} [{row['source']}] {row['word']}")
        else:
            print("\n没有需要归档的多词改错。")
        if not args.apply:
            print("\n只读模式；确认后加 --apply 归档。")
            return 0
        archived = apply(conn, report)
        audit = _write_audit(report, archived)
        print(f"\n已归档 {archived} 条（可恢复）；审计文件：{audit}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
