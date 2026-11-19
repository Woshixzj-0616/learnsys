"""生词明显变体合并：Caravans/caravan、the Silk Road/Silk Road、斜杠同义项等。

规则只认高置信变体（见 `learnsys/store/wordkey.py`）：
大小写/标点、冠词 the、单复数、斜杠同义项、括号缩写；
`high-speed rail` / `high-speed railway` 这类同义词只报告，不自动合并。

同时清理与 active 生词重叠的每日积累翻译卡状态：
同一英文只保留生词本里的那张，避免词 tab 出现两张同词卡。

默认只读；`--apply` 才写库，写前自动备份。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.store.wordkey import (is_plural_phrase, meanings_compatible,
                                    word_aliases)  # noqa: E402


def _display_score(item: dict) -> float:
    word = str(item.get("word") or "")
    meaning = str(item.get("meaning") or "")
    score = 0.0
    if "/" not in word:
        score += 2
    if "(" not in word:
        score += 1
    if not is_plural_phrase(word):
        score += 1
    # 释义更完整的旧条目优先保留，避免合并后把「｜备注」丢掉。
    return score - len(word) * 0.01 + min(len(meaning), 120) / 1000


def _primary(group: list[dict]) -> dict:
    return max(group, key=lambda item: (_display_score(item),
                                        -int(item.get("id") or 0)))


def _merge_fields(target: dict, source: dict) -> dict:
    updates = {}
    for key in ("meaning", "context", "phonetic"):
        if source.get(key) and not target.get(key):
            updates[key] = source[key]
    # 同词条目的释义通常是「词义｜备注」；保留更完整的那份。
    target_meaning = str(target.get("meaning") or "")
    source_meaning = str(source.get("meaning") or "")
    if (source_meaning and target_meaning
            and target_meaning in source_meaning
            and len(source_meaning) > len(target_meaning)):
        updates["meaning"] = source_meaning
    return updates


def _copy_state(conn, source_id: int, target_id: int) -> None:
    if store.get_review_state(conn, "vocab", target_id) is not None:
        return
    state = store.get_review_state(conn, "vocab", source_id)
    if state is None:
        return
    store.save_review_state(
        conn, "vocab", target_id,
        state=state.get("state") or "new", due=state.get("due") or "",
        stability=state.get("stability") or 0,
        difficulty=state.get("difficulty") or 0,
        reps=state.get("reps") or 0, lapses=state.get("lapses") or 0,
        last_review=state.get("last_review") or "",
        scheduled_days=state.get("scheduled_days") or 0,
        elapsed_days=state.get("elapsed_days") or 0)


def _tokens(word: str) -> set[str]:
    aliases = word_aliases(word)
    if not aliases:
        return set()
    return set(min(aliases, key=len).split())


def _suspected(items: list[dict], grouped_ids: set[int]) -> list[tuple[dict, dict]]:
    """同义但拼写不同的候选：token 重合度 ≥ 0.5，且不在已合并组里。"""
    rows = [item for item in items if int(item["id"]) not in grouped_ids]
    found: list[tuple[dict, dict]] = []
    for index, left in enumerate(rows):
        left_tokens = _tokens(left.get("word"))
        if not left_tokens:
            continue
        for right in rows[index + 1:]:
            right_tokens = _tokens(right.get("word"))
            if not right_tokens:
                continue
            union = left_tokens | right_tokens
            if not union:
                continue
            overlap = len(left_tokens & right_tokens) / len(union)
            if overlap >= 0.5 and not (word_aliases(left.get("word"))
                                       & word_aliases(right.get("word"))):
                found.append((left, right))
    return found[:30]


def _meanings_conflict(group: list[dict]) -> bool:
    """同词形但中文释义完全不搭（如 glass 玻璃 / glasses 眼镜）时不自动合并。"""
    for index, left in enumerate(group):
        for right in group[index + 1:]:
            left_meaning = str(left.get("meaning") or "")
            right_meaning = str(right.get("meaning") or "")
            if (left_meaning and right_meaning
                    and not meanings_compatible(left_meaning, right_meaning)):
                return True
    return False


def collect(conn) -> dict:
    items = store.list_vocab(conn, limit=500)["items"]
    groups = store.variant_groups(items)
    plans = []
    conflicts = []
    grouped_ids: set[int] = set()
    for group in groups:
        grouped_ids.update(int(item["id"]) for item in group)
        if _meanings_conflict(group):
            conflicts.append(group)
            continue
        primary = _primary(group)
        plans.append({
            "primary": primary,
            "others": [item for item in group if item["id"] != primary["id"]],
        })
    return {"items": items, "plans": plans, "conflicts": conflicts,
            "suspected": _suspected(items, grouped_ids)}


def apply(conn, report: dict) -> dict:
    merged = archived = 0
    for plan in report["plans"]:
        primary = plan["primary"]
        target = store.get_vocab(conn, primary["id"]) or primary
        for other in plan["others"]:
            _copy_state(conn, int(other["id"]), int(primary["id"]))
            updates = _merge_fields(target, other)
            if updates:
                target = store.update_vocab(conn, int(primary["id"]),
                                            **updates) or target
            store.update_vocab(conn, int(other["id"]), status="archived")
            archived += 1
        merged += 1
    suppressed = store.suppress_accum_vocab_duplicates(conn)
    return {"merged": merged, "archived": archived,
            "suppressed": suppressed}


def render(report: dict, applied: dict | None = None) -> str:
    lines = ["生词变体合并（只读）" if applied is None else "生词变体合并（已执行）",
             f"活动生词：{len(report['items'])} 条"]
    lines.append(f"可自动合并的组：{len(report['plans'])} 组")
    for plan in report["plans"]:
        primary = plan["primary"]
        lines.append(f"  保留 #{primary['id']} {primary['word']}")
        for other in plan["others"]:
            lines.append(f"    并入 #{other['id']} {other['word']}"
                         f"（{other.get('meaning') or '无释义'}）")
    lines.append(f"同词形但释义不同、未合并：{len(report['conflicts'])} 组")
    for group in report["conflicts"]:
        lines.append("  " + " ↔ ".join(
            f"#{item['id']} {item['word']}（{item.get('meaning') or '无释义'}）"
            for item in group))
    lines.append("疑似同义、未自动合并："
                 + (str(len(report["suspected"])) + " 对"
                    if report["suspected"] else "0 对"))
    for left, right in report["suspected"]:
        lines.append(f"  #{left['id']} {left['word']} ↔ "
                     f"#{right['id']} {right['word']}")
    if applied is None:
        lines.append("预检：加 --apply 才会写库。")
    else:
        lines.append("执行结果：合并 {merged} 组，归档 {archived} 条，"
                     "退出复习的同词 accum 卡 {suppressed} 张".format(**applied))
    return "\n".join(lines)


def _backup(db_path: pathlib.Path) -> pathlib.Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.name}.bak-{stamp}-生词变体合并")
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生词变体合并（只读默认）")
    parser.add_argument("--db", default=str(config.db_path()))
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args(argv)

    db_path = pathlib.Path(args.db)
    backup = None
    if args.apply:
        if not db_path.is_file():
            print(f"数据库不存在：{db_path}")
            return 1
        backup = _backup(db_path)
        print(f"已备份：{backup}")
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
