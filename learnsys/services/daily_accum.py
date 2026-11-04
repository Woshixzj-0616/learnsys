"""每日积累：写作句型 + 翻译短语 + 你自己的纠音点。

- 当天第一次打开时生成，生成后当天冻结；
- 写作取 `patterns.json`（句型 + 用途 + 例句），翻译取 `phrases.json`
  的高频短语 + 跨篇目主题词，都不调模型；
- 纠音从 `cet6_progress.note` 解析，规则在 `services.cet6_pron`；
- 条目存进 `cet6_accum_items`，状态只影响进度与后续筛选。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store
from learnsys.services.cet6 import pron as cet6_pron
from learnsys.train import content as train_content

KINDS = ("writing", "translation", "pron")
KIND_LABELS = {"writing": "写作句型", "translation": "翻译短语",
               "pron": "每日纠音"}
STATUSES = ("new", "read", "mastered")
WRITING_PER_DAY = 2
TERMS_PER_DAY = 8
PHRASE_PER_DAY = 4          # 高频短语；剩下 4 个来自不同篇目的主题词
PRON_PER_DAY = 5
PLAYABLE_PRON_PER_DAY = 4   # 优先放能逐词播放的；留 1 条只给整句的
PRON_GAP_DAYS = 3
# 高频短语从 2026-11-02 上线日起按 4 条/天轮换，首日从库头开始，
# 让红包、一带一路这些第一批就能看到；换短语库时改这个基准。
PHRASE_EPOCH = dt.date(2026, 11, 2)
# 写作句型从 2026-11-04 起按 2 条/天轮换，首日从库头开始。
# 旧实现每天只平移 1 条，今天的第一条正好是昨天的第二条，相邻两天必重复。
WRITING_EPOCH = dt.date(2026, 11, 4)
# 内容结构 / 轮换口径变了就升这个号：当天已生成的写作/翻译会重新生成，往期历史不动。
ACCUM_VERSION = 4


def _today() -> str:
    return dt.date.today().isoformat()


def _ordinal(day: str) -> int:
    return dt.date.fromisoformat(str(day)[:10]).toordinal()


def _daily_start(day: str, per_day: int, size: int, epoch: dt.date) -> int:
    """每天按 per_day 条平移；相邻两天的窗口不重叠。"""
    return ((_ordinal(day) - epoch.toordinal()) * int(per_day)) % size


def _writing_payloads(day: str) -> list[dict]:
    """写作积累只取句型库：句型 + 中文用途 + 例句 + 译文。"""
    rows = train_content.writing_patterns()
    if not rows:
        return []
    size = len(rows)
    start = _daily_start(day, WRITING_PER_DAY, size, WRITING_EPOCH)
    positions = [start]
    if size > 1:
        positions.append((start + 1) % size)
    result: list[dict] = []
    for position in positions[:WRITING_PER_DAY]:
        item = rows[position]
        result.append({
            "ref_key": f"pattern:{item.get('id')}",
            "payload": {
                "pattern": str(item.get("pattern") or "").strip(),
                "zh": str(item.get("zh") or "").strip(),
                "group": str(item.get("group") or "").strip(),
                "example": str(item.get("example") or "").strip(),
                "example_zh": str(item.get("example_zh") or "").strip(),
                "note": str(item.get("note") or "").strip(),
                "source_id": str(item.get("id") or ""),
                "v": ACCUM_VERSION,
            },
        })
    return result


def _theme_term_groups() -> list[tuple[dict, list[dict]]]:
    """按篇目分组，一天从不同篇目各取一个词，避免整天只考一个主题。"""
    groups: list[tuple[dict, list[dict]]] = []
    seen: set[str] = set()
    for item in train_content.library()["translation"]:
        terms = []
        for term in item.get("terms") or []:
            if not isinstance(term, dict):
                continue
            zh = str(term.get("zh") or "").strip()
            if not zh or zh in seen:
                continue
            seen.add(zh)
            terms.append(term)
        if terms:
            groups.append((item, terms))
    return groups


def _translation_payloads(day: str) -> list[dict]:
    result: list[dict] = []
    chosen: set[str] = set()
    ordinal = _ordinal(day)

    phrases = [row for row in train_content.translation_phrases()
               if isinstance(row, dict) and str(row.get("zh") or "").strip()]
    if phrases:
        size = len(phrases)
        start = _daily_start(day, PHRASE_PER_DAY, size, PHRASE_EPOCH)
        for offset in range(min(PHRASE_PER_DAY, size)):
            phrase = phrases[(start + offset) % size]
            zh = str(phrase.get("zh") or "").strip()
            if zh in chosen:
                continue
            chosen.add(zh)
            result.append({
                "ref_key": f"phrase:{phrase.get('id')}",
                "payload": {
                    "zh": zh,
                    "en": str(phrase.get("en") or "").strip(),
                    "note": str(phrase.get("note") or "").strip(),
                    "theme": str(phrase.get("theme") or "").strip(),
                    "tag": "高频短语",
                    "source_id": str(phrase.get("id") or ""),
                    "v": ACCUM_VERSION,
                },
            })

    groups = _theme_term_groups()
    need = max(0, TERMS_PER_DAY - len(result))
    if groups and need:
        size = len(groups)
        start = ordinal % size
        for offset in range(size):
            if need <= 0:
                break
            item, terms = groups[(start + offset) % size]
            for pick in range(len(terms)):
                # 只跟日期走，不再加 offset：offset 每天减 1 会和日期的 +1
                # 互相抵消，导致同一组主题词在相邻两天挑到同一个词。
                term = terms[(ordinal + pick) % len(terms)]
                zh = str(term.get("zh") or "").strip()
                if not zh or zh in chosen:
                    continue
                chosen.add(zh)
                result.append({
                    "ref_key": f"term:{item.get('id')}:{zh}",
                    "payload": {
                        "zh": zh,
                        "en": str(term.get("en") or "").strip(),
                        "note": str(term.get("note") or "").strip(),
                        "theme": str(item.get("theme") or "").strip(),
                        "tag": "主题词",
                        "source_id": f"{item.get('id')}:{zh}",
                        "v": ACCUM_VERSION,
                    },
                })
                need -= 1
                break
    return result


def _pron_payloads(conn, day: str) -> list[dict]:
    cet6_pron.ensure_pool(conn)
    since = (dt.date.fromisoformat(day) - dt.timedelta(days=PRON_GAP_DAYS)).isoformat()
    candidates = store.pron_candidates(
        conn, since=since, limit=PRON_PER_DAY * 6)
    playable: list[dict] = []
    others: list[dict] = []
    for item in candidates:
        segment = cet6_pron.audio_segment(
            item["paper_title"], item["section"], item["item"],
            item["sentence"], item["target"])
        (playable if segment else others).append(item)
    picked = playable[:PLAYABLE_PRON_PER_DAY]
    picked += others[:max(0, PRON_PER_DAY - len(picked))]
    used = {int(item["id"]) for item in picked}
    for item in playable + others:
        if len(picked) >= PRON_PER_DAY:
            break
        if int(item["id"]) not in used:
            picked.append(item)
            used.add(int(item["id"]))
    result: list[dict] = []
    for item in picked:
        payload = cet6_pron.payload(conn, item)
        payload["v"] = ACCUM_VERSION
        result.append({
            "ref_key": f"pron:{item['id']}",
            "payload": payload,
            "pron_id": item["id"],
        })
    return result


def _stale(items: list[dict], kind: str) -> bool:
    return any(str(item["payload"].get("v") or "") != str(ACCUM_VERSION)
               for item in items if item["kind"] == kind)


def ensure_day(conn, day: str | None = None) -> None:
    """只生成今天，且每类只补缺失的部分；历史日期不补。

    写作/翻译的结构由 `ACCUM_VERSION` 控制：旧结构的当天条目会被删掉重生成，
    这样升级后当天就能看到新卡片；往期历史保持原样。
    """
    day = str(day or _today())[:10]
    if day != _today():
        return
    existing = store.accum_items(conn, day)
    for kind in ("writing", "translation"):
        if _stale(existing, kind):
            store.delete_accum_kind(conn, day, kind)
    existing = store.accum_items(conn, day)
    kinds = {item["kind"] for item in existing}
    if "writing" not in kinds:
        for row in _writing_payloads(day):
            store.add_accum(conn, day=day, kind="writing",
                            ref_key=row["ref_key"], payload=row["payload"])
    if "translation" not in kinds:
        for row in _translation_payloads(day):
            store.add_accum(conn, day=day, kind="translation",
                            ref_key=row["ref_key"], payload=row["payload"])
    if "pron" not in kinds:
        rows = _pron_payloads(conn, day)
        for row in rows:
            store.add_accum(conn, day=day, kind="pron",
                            ref_key=row["ref_key"], payload=row["payload"])
        store.mark_pron_used(conn, [row["pron_id"] for row in rows], day)


def _day_complete(conn, day: str) -> bool:
    counts = store.accum_counts(conn, day)
    total = sum(value["total"] for value in counts.values())
    done = sum(value["done"] for value in counts.values())
    return total > 0 and done >= total


def streak(conn, day: str | None = None) -> int:
    """连续「全部过完」的天数；今天没做完就从昨天开始数。"""
    cursor = dt.date.fromisoformat(str(day or _today())[:10])
    if not _day_complete(conn, cursor.isoformat()):
        cursor -= dt.timedelta(days=1)
    count = 0
    while _day_complete(conn, cursor.isoformat()):
        count += 1
        cursor -= dt.timedelta(days=1)
    return count


def summary(conn, day: str | None = None) -> dict:
    day = str(day or _today())[:10]
    counts = store.accum_counts(conn, day)
    grouped = {kind: counts.get(kind, {"total": 0, "done": 0})
               for kind in KINDS}
    total = sum(value["total"] for value in grouped.values())
    done = sum(value["done"] for value in grouped.values())
    return {
        "day": day,
        "is_today": day == _today(),
        "counts": grouped,
        "total": total,
        "done": done,
        "streak": streak(conn, day),
    }


def today_summary(conn, day: str | None = None) -> dict:
    day = str(day or _today())[:10]
    ensure_day(conn, day)
    return summary(conn, day)


def list_day(conn, day: str | None = None) -> dict:
    day = str(day or _today())[:10]
    ensure_day(conn, day)
    items = {kind: [] for kind in KINDS}
    for item in store.accum_items(conn, day):
        if item["kind"] in items:
            items[item["kind"]].append(item)
    # 纠音音频按当前试卷重新算一次：历史条目也不会带着旧的错误偏移播放。
    for item in items["pron"]:
        pron_id = int(item["payload"].get("pron_id") or 0)
        row = store.pron_item(conn, pron_id) if pron_id else None
        if row is not None:
            fresh = cet6_pron.payload(conn, row)
            fresh["v"] = item["payload"].get("v", ACCUM_VERSION)
            item["payload"] = fresh
    return {**summary(conn, day), "items": items}


def mark(conn, item_id: int, status: str) -> dict:
    status = str(status or "").strip()
    if status not in STATUSES:
        raise ValueError("状态只能是 new / read / mastered")
    item = store.accum_item(conn, int(item_id))
    if item is None:
        raise LookupError("这条积累不存在")
    store.set_accum_status(conn, int(item_id), status)
    if item["kind"] == "pron":
        pron_id = int(item["payload"].get("pron_id") or 0)
        if pron_id:
            store.set_pron_status(
                conn, pron_id, "mastered" if status == "mastered" else "practicing")
    return summary(conn, item["day"])


def mark_all(conn, day: str | None = None) -> dict:
    """当天还没动过的条目一次标已读；纠音点进 practicing，不直接算掌握。"""
    day = str(day or _today())[:10]
    ensure_day(conn, day)
    store.set_all_accum_status(conn, day, "read")
    for item in store.accum_items(conn, day):
        if item["kind"] != "pron" or item["status"] != "read":
            continue
        pron_id = int(item["payload"].get("pron_id") or 0)
        if pron_id:
            store.set_pron_status(conn, pron_id, "practicing")
    return summary(conn, day)


def add_term_to_vocab(conn, item_id: int) -> dict:
    item = store.accum_item(conn, int(item_id))
    if item is None:
        raise LookupError("这条积累不存在")
    if item["kind"] != "translation":
        raise ValueError("只有翻译词可以加入生词本")
    payload = item["payload"]
    meaning = str(payload.get("zh") or "").strip()
    note = str(payload.get("note") or "").strip()
    if note:
        meaning = f"{meaning}｜{note}" if meaning else note
    vocab, created = store.add_vocab(
        conn, word=str(payload.get("en") or "").strip(),
        meaning=meaning, source="daily")
    store.set_accum_status(conn, int(item_id), "read")
    return {"vocab": vocab, "created": created,
            "summary": summary(conn, item["day"])}


def history(conn, limit: int = 30) -> dict:
    return {"days": store.accum_days(conn, limit=limit)}
