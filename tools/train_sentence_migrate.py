"""把翻译错题卡从「片段卡」改写成「整句卡」，并清理生词本里的非词条。

背景：2.56.1 起一句一译/整篇翻译把每个 must_fix 同时写成两张碎片——
错题本 `改译：片段`、生词本 `fix`。复习时看不到整句，生词本里混进
`Schools should`、`The government has invested` 这类句子片段。

规则：
- 错题本：同一句的碎片卡合并成一张整句卡（正面=中文原句或完整英文句，
  背面=该句全部错误点）；保留其中一张卡的复习状态，其余删除。
- 生词本：旧条目按 meaning 里的错误类型重新过一遍 `train.lexical` 准入；
  语法/标点/误译等一律归档；整篇翻译的条目再按形态与已知短语白名单判断。
  归档只改 `status`，不删除，可恢复。

默认只读；`--apply` 才写库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.train import content, lexical, review  # noqa: E402

# 历史整篇翻译里形态超过 3 词、但确实是固定表达的条目；迁移时显式保留。
KEEP_PHRASES = {
    "the first day of the lunar new year",
    "abundance year after year",
    "pay new year greetings",
    "pay new year greetings to",
    "stay up late to see the old year out",
}
_TYPE_ORDER = ("拼写", "语法", "标点", "结构", "漏译", "误译", "改变原意",
               "中式英语", "搭配", "术语", "用词")


def _loads(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _latest(conn, prompt_id: str, sentence_mode: bool):
    condition = "mode = 'sentence'" if sentence_mode else "mode <> 'sentence'"
    return conn.execute(
        "SELECT id, text, band_json FROM train_submissions "
        f"WHERE prompt_id = ? AND {condition} AND status = 'reviewed' "
        "ORDER BY id DESC LIMIT 1", (prompt_id,)).fetchone()


def _errors(row, sentence_mode: bool) -> list[dict]:
    data = _loads(row[2] if row else "")
    key = "must_fix" if sentence_mode else "errors"
    return [item for item in data.get(key) or [] if isinstance(item, dict)]


def _target(source_id: str) -> tuple[str, str]:
    if source_id.startswith("sentence:"):
        return "sentence", source_id.split(":")[1]
    if source_id.startswith("translation:"):
        return "whole", source_id.split(":")[1]
    return "", ""


def _fallback_row(fragment: str, answer: str, note: str) -> dict:
    return {"quote": fragment, "fix": answer, "why": note, "type": "", "severity": "严重"}


def collect_cards(conn) -> dict:
    cards = conn.execute(
        "SELECT id, source_id, question, answer, my_answer, tags, note "
        "FROM wrong_items WHERE source = 'translation' ORDER BY id").fetchall()
    groups: dict[str, dict] = {}
    skipped = []
    for card_id, source_id, question, answer, my_answer, _tags, note in cards:
        kind, prompt_id = _target(source_id or "")
        if not kind:
            skipped.append({"id": card_id, "reason": "来源不是训练批改", "source_id": source_id})
            continue
        sentence_mode = kind == "sentence"
        submission = _latest(conn, prompt_id, sentence_mode)
        text = submission[1] if submission else ""
        errors = _errors(submission, sentence_mode)
        fragment = str(my_answer or "").strip()
        if not fragment:
            fragment = re.sub(r"^(改错|改译)[：:]\s*", "", str(question or "")).strip()

        if sentence_mode:
            item = content.sentence(prompt_id) or {}
            new_id = f"sentence:{prompt_id}"
            group = groups.setdefault(new_id, {
                "kind": kind, "prompt_id": prompt_id, "item": item,
                "text": text, "minimal_fix": _loads(
                    submission[2] if submission else "").get("minimal_fix", ""),
                "sentence": item.get("zh") or prompt_id,
                "errors": errors, "card_ids": [],
            })
            if not group["errors"]:
                group["errors"] = [_fallback_row(fragment, answer, note)]
            group["card_ids"].append(card_id)
            continue

        if text and fragment:
            sentence = review.sentence_around(text, fragment)
        else:
            sentence = fragment or str(question or "")
        digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:10]
        new_id = f"translation:{prompt_id}:{digest}"
        rows = [row for row in errors
                if review.sentence_around(text, row.get("quote", "")) == sentence]
        group = groups.setdefault(new_id, {
            "kind": kind, "prompt_id": prompt_id, "item": {},
            "text": text, "minimal_fix": "", "sentence": sentence,
            "errors": rows, "card_ids": [],
        })
        if not group["errors"]:
            group["errors"] = [_fallback_row(fragment, answer, note)]
        group["card_ids"].append(card_id)

    for new_id, group in groups.items():
        if group["kind"] == "sentence":
            card = review.sentence_card(
                group["item"], group["text"], group["errors"], group["minimal_fix"])
        else:
            card = review.translation_sentence_card(
                f"translation:{group['prompt_id']}", group["sentence"], group["errors"])
        existing = conn.execute(
            "SELECT id FROM wrong_items WHERE source = 'translation' AND source_id = ?",
            (new_id,)).fetchone()
        group["card"] = card
        group["card_ids"].sort()
        group["survivor"] = int(existing[0]) if existing else group["card_ids"][0]
        group["new_id"] = new_id
    return {"groups": list(groups.values()), "skipped": skipped,
            "cards": len(cards)}


def _type_from_meaning(meaning: str) -> str:
    for kind in _TYPE_ORDER:
        if kind in meaning:
            return kind
    return ""


def collect_vocab(conn) -> dict:
    items = store.list_vocab(conn, limit=500, status="active")["items"]
    # 去重时优先保留无引号写法：先处理无引号条目，带引号的同词后到、按重复归档。
    items = sorted(items, key=lambda item: (
        '"' in str(item.get("word") or ""),
        "“" in str(item.get("word") or ""),
        int(item.get("id") or 0)))
    decisions, seen = [], set()
    for item in items:
        source = str(item.get("source") or "")
        word = str(item.get("word") or "")
        meaning = str(item.get("meaning") or "")
        action, reason = "keep", ""
        if source == "sentence":
            if not lexical.is_lexical_shape(word):
                kind = _type_from_meaning(meaning)
                action, reason = "archive", f"{kind or '非词条'}片段"
        elif source == "translation":
            canonical = word.strip('"“”').lower()
            if canonical in seen:
                action, reason = "archive", "重复条目"
            elif canonical not in KEEP_PHRASES and not lexical.is_lexical_shape(word):
                action, reason = "archive", "不是词条形态"
            seen.add(canonical)
        decisions.append({"id": item["id"], "word": word, "source": source,
                          "action": action, "reason": reason})
    return {"items": items, "decisions": decisions}


def apply(conn, cards: dict, vocab: dict) -> dict:
    deleted = rewritten = archived = 0
    for group in cards["groups"]:
        survivor = group["survivor"]
        ids = group["card_ids"]
        if store.get_review_state(conn, "wrong", survivor) is None:
            for card_id in ids:
                if card_id == survivor:
                    continue
                donor = store.get_review_state(conn, "wrong", card_id)
                if donor:
                    store.save_review_state(
                        conn, "wrong", survivor,
                        state=donor.get("state") or "new",
                        due=donor.get("due") or "",
                        stability=donor.get("stability") or 0,
                        difficulty=donor.get("difficulty") or 0,
                        reps=donor.get("reps") or 0,
                        lapses=donor.get("lapses") or 0,
                        last_review=donor.get("last_review") or "",
                        scheduled_days=donor.get("scheduled_days") or 0,
                        elapsed_days=donor.get("elapsed_days") or 0)
                    break
        for card_id in ids:
            if card_id != survivor:
                store.delete_wrong_item(conn, card_id)
                deleted += 1
        card = group["card"]
        store.rewrite_wrong_item(
            conn, survivor, source_id=card["source_id"],
            question=card["question"], answer=card["answer"],
            my_answer=card["my_answer"], tags=card["tags"], note=card["note"])
        rewritten += 1
    for row in vocab["decisions"]:
        if row["action"] == "archive":
            store.update_vocab(conn, row["id"], status="archived")
            archived += 1
    return {"deleted": deleted, "rewritten": rewritten, "archived": archived}


def render(cards: dict, vocab: dict, applied: dict | None = None) -> str:
    lines = ["六级训练错题/生词迁移（只读）" if applied is None
             else "六级训练错题/生词迁移（已执行）"]
    archive = [row for row in vocab["decisions"] if row["action"] == "archive"]
    keep = [row for row in vocab["decisions"] if row["action"] == "keep"]
    lines.append(f"翻译错题卡：{cards['cards']} 张 → {len(cards['groups'])} 张整句卡")
    for group in cards["groups"]:
        card = group["card"]
        lines.append(f"  {group['new_id']}  {len(group['card_ids'])} 张 → 1 张"
                     f"  {card['question'][:48]}")
    if cards["skipped"]:
        lines.append("跳过：" + "；".join(
            f"#{row['id']} {row['reason']}" for row in cards["skipped"]))
    lines.append(f"生词本：活动 {len(vocab['items'])} 条；"
                 f"建议归档 {len(archive)} 条，保留 {len(keep)} 条")
    for row in archive:
        lines.append(f"  [归档] #{row['id']}  {row['word']}  "
                     f"[{row['source']}] {row['reason']}")
    if applied is not None:
        lines.append("执行结果：合并/删除 {deleted} 张旧卡，重写 {rewritten} 张，"
                     "归档生词 {archived} 条".format(**applied))
    else:
        lines.append("预检：加 --apply 才会写库。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="翻译错题改整句卡 + 生词本准入清理（只读默认）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args(argv)
    conn = store.connect(pathlib.Path(args.db))
    try:
        cards = collect_cards(conn)
        vocab = collect_vocab(conn)
        applied = apply(conn, cards, vocab) if args.apply else None
        print(render(cards, vocab, applied))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
