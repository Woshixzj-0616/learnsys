"""每日积累与生词本的去重规则：同词 accum 卡退出复习。

从 `store/review.py` 拆出，守住 500 行门禁；`seed_review_states` 仍调用这里。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK
from .wordkey import variant_groups, word_aliases


def active_vocab_aliases(conn: sqlite3.Connection) -> set[str]:
    """active 生词的 alias 集合；归档的变体条目也算桥。

    合并后只留下干净词形（如 telemedicine），但归档的斜杠条目
    （remote medicine / telemedicine）仍然是 alias 桥；不算进来，
    每日积累里的 remote medicine 就会重新冒出来。
    """
    rows = conn.execute(
        "SELECT id, word, status FROM vocab_items").fetchall()
    items = [{"id": int(row[0]), "word": row[1] or "", "status": row[2] or ""}
             for row in rows]
    aliases: set[str] = set()
    grouped_ids: set[int] = set()
    for group in variant_groups(items):
        ids = {int(item["id"]) for item in group}
        grouped_ids |= ids
        if any(item["status"] == "active" for item in group):
            for item in group:
                aliases |= word_aliases(item["word"])
    for item in items:
        if item["status"] == "active" and int(item["id"]) not in grouped_ids:
            aliases |= word_aliases(item["word"])
    return aliases


def _active_vocab_alias_set(conn: sqlite3.Connection) -> set[str]:
    return active_vocab_aliases(conn)


def _accum_english(payload_json) -> str:
    try:
        payload = json.loads(payload_json or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("en") or "").strip()


def _suppress_duplicate_accum(conn: sqlite3.Connection,
                              vocab_aliases: set[str]) -> int:
    """同词 accum 翻译卡只留最早一张；命中 active 生词的也退出复习。

    每日积累和生词本都会产生词卡，同一英文在词 tab 出现两次没有学习价值。
    这里只删 `review_state`，`cet6_accum_items` 历史仍保留。
    """
    rows = conn.execute(
        "SELECT r.item_id, a.day, a.payload_json FROM review_state r "
        "JOIN cet6_accum_items a ON r.item_type = 'accum' AND a.id = r.item_id "
        "WHERE a.kind = 'translation' ORDER BY a.day, a.id").fetchall()
    kept: list[set[str]] = []
    drop: list[int] = []
    for item_id, _day, payload_json in rows:
        aliases = word_aliases(_accum_english(payload_json))
        if not aliases:
            continue
        if aliases & vocab_aliases:
            drop.append(int(item_id))
            continue
        if any(aliases & seen for seen in kept):
            drop.append(int(item_id))
            continue
        kept.append(aliases)
    if drop:
        marks = ",".join("?" * len(drop))
        with _LOCK:
            conn.execute(
                f"DELETE FROM review_state WHERE item_type = 'accum' "
                f"AND item_id IN ({marks})", drop)
            conn.commit()
    return len(drop)


def suppress_accum_vocab_duplicates(conn: sqlite3.Connection) -> int:
    """公开入口：清理与 active 生词重叠/彼此重复的 accum 翻译卡状态。"""
    return _suppress_duplicate_accum(conn, _active_vocab_alias_set(conn))


