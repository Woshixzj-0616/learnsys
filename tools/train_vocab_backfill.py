"""把六级训练历史批改里的问题回填进生词本。

只读默认；`--apply` 才写库。来源：
- `train_submissions.mode='sentence'` 的 `must_fix`（一句一译）；
- 整篇翻译/写作的 `errors`（`band_json`）。
过滤：空 fix、fix=quote、fix 超过 120 字、去掉空白/标点/大小写后完全相同的纯格式问题；
不是词条的（语法/标点/误译、超过词条形态）也跳过——它们由整句错题卡承担。
同一批按英文词头去重，库里已有的由 `store.add_vocab` 自动合并。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.train import content, lexical  # noqa: E402

MAX_WORD = 120
CJK = re.compile(r"[一-鿿]")


def _has_cjk(text: str) -> bool:
    return bool(CJK.search(str(text or "")))


def _content_key(text: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(text or "").lower())


def _norm_word(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _title(kind: str, mode: str, prompt_id: str) -> str:
    if mode == "sentence":
        item = content.sentence(prompt_id) or {}
        return str(item.get("source_title") or "一句一译")
    pack = content.pack(kind, prompt_id) or {}
    return str(pack.get("title") or ("六级训练 · " + ("翻译" if kind == "translation" else "写作")))


def _context(kind: str, mode: str, prompt_id: str, quote: str, fix: str) -> str:
    if mode == "sentence":
        item = content.sentence(prompt_id) or {}
        text = f"一句一译：{item.get('zh') or ''}"
        if quote:
            text += f" ｜ 我当时写：{quote}"
        return text
    title = _title(kind, mode, prompt_id)
    if kind == "translation":
        return f"整篇翻译：{title} ｜ 改译：{quote} → {fix}"
    return f"写作：{title} ｜ 原句：{quote} → 建议：{fix}"


def collect(conn) -> dict:
    existing = {row["normalized"] for row in store.list_vocab(conn, limit=500)["items"]}
    seen: set[str] = set()
    rows, skipped = [], []
    term_cache: dict[str, list] = {}
    submissions = conn.execute(
        "SELECT id, kind, mode, prompt_id, band_json, created_at FROM train_submissions "
        "WHERE status = 'reviewed' AND band_json IS NOT NULL AND band_json <> '' "
        "ORDER BY id").fetchall()
    for sid, kind, mode, prompt_id, band_json, created_at in submissions:
        try:
            data = json.loads(band_json or "{}")
        except (TypeError, ValueError):
            continue
        items = data.get("must_fix") if mode == "sentence" else data.get("errors")
        for item in items or []:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()
            fix = str(item.get("fix") or "").strip()
            why = str(item.get("why") or "").strip()
            error_type = str(item.get("type") or "").strip()
            if prompt_id not in term_cache:
                pack = (content.pack("translation", prompt_id) or {}
                        if kind == "translation" else {})
                term_cache[prompt_id] = pack.get("terms") or []
            entry = lexical.as_vocab_entry(
                error_type=error_type, quote=quote, fix=fix, why=why,
                terms=term_cache[prompt_id])
            reason = ""
            if not fix:
                reason = "空 fix"
            elif fix == quote:
                reason = "fix 与 quote 相同"
            elif len(fix) > MAX_WORD:
                reason = "fix 超过 120 字"
            elif _content_key(quote) == _content_key(fix):
                reason = "纯格式（空白/标点/大小写）"
            elif entry is None:
                reason = "不是词条（进整句错题卡）"
            elif _norm_word(fix) in existing:
                reason = "生词本已有"
            elif _norm_word(fix) in seen:
                reason = "本批重复"
            if reason:
                skipped.append({"submission": sid, "prompt_id": prompt_id,
                                "quote": quote, "fix": fix, "reason": reason})
                continue
            seen.add(_norm_word(fix))
            rows.append({
                "submission": sid, "kind": kind, "mode": mode,
                "prompt_id": prompt_id, "quote": quote, "fix": fix,
                "why": why, "type": error_type, "created_at": created_at,
                "word": entry[0], "meaning": entry[1],
            })
    return {"rows": rows, "skipped": skipped, "submissions": len(submissions)}


def apply(conn, report: dict) -> dict:
    added = merged = 0
    for row in report["rows"]:
        _, created = store.add_vocab(
            conn, word=row["word"], meaning=row["meaning"],
            context=_context(row["kind"], row["mode"], row["prompt_id"],
                             row["quote"], row["fix"]),
            paper_id=row["prompt_id"],
            paper_title=_title(row["kind"], row["mode"], row["prompt_id"]),
            source="sentence" if row["mode"] == "sentence" else row["kind"])
        added += 1 if created else 0
        merged += 0 if created else 1
    return {"added": added, "merged": merged}


def render(report: dict, applied: dict | None = None) -> str:
    lines = ["六级训练 → 生词本回填（只读）" if applied is None else "六级训练 → 生词本回填（已执行）",
             f"已批改提交：{report['submissions']} 条",
             f"可新增：{len(report['rows'])} 条；跳过：{len(report['skipped'])} 条"]
    for row in report["rows"]:
        lines.append(f"  #{row['submission']} {row['prompt_id']}  {row['fix']}"
                     f"  ← {row['quote']}  [{row['mode']}]")
    reasons: dict[str, int] = {}
    for row in report["skipped"]:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    if reasons:
        lines.append("跳过原因：" + "；".join(f"{k} {v}" for k, v in reasons.items()))
    if applied is not None:
        lines.append(f"执行结果：新增 {applied['added']} 条，合并 {applied['merged']} 条")
    else:
        lines.append("预检：加 --apply 才会写库。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="六级训练历史问题回填生词本（只读默认）")
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
