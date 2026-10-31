"""每日积累：写作好句 + 翻译重点词 + 你自己的纠音点。

- 当天第一次打开时生成，生成后当天冻结；
- 写作/翻译只从题库取，不调模型；
- 纠音从 `cet6_progress.note` 解析，规则在 `services.cet6_pron`；
- 条目存进 `cet6_accum_items`，状态只影响进度与后续筛选。
"""
from __future__ import annotations

import datetime as dt

from learnsys import store
from learnsys.services import cet6_pron
from learnsys.train import content as train_content

KINDS = ("writing", "translation", "pron")
KIND_LABELS = {"writing": "写作好句", "translation": "翻译重点词",
               "pron": "每日纠音"}
STATUSES = ("new", "read", "mastered")
WRITING_PER_DAY = 2
TERMS_PER_DAY = 8
PRON_PER_DAY = 5
PRON_GAP_DAYS = 3


def _today() -> str:
    return dt.date.today().isoformat()


def _ordinal(day: str) -> int:
    return dt.date.fromisoformat(str(day)[:10]).toordinal()


def _upgrades() -> list[tuple[dict, int, dict]]:
    rows: list[tuple[dict, int, dict]] = []
    for item in train_content.library()["writing"]:
        for index, upgrade in enumerate(item.get("upgrades") or []):
            if not isinstance(upgrade, dict):
                continue
            if not str(upgrade.get("high") or "").strip():
                continue
            rows.append((item, index, upgrade))
    return rows


def _writing_payloads(day: str) -> list[dict]:
    rows = _upgrades()
    if not rows:
        return []
    size = len(rows)
    starts = [_ordinal(day) % size, (_ordinal(day) + size // 2) % size]
    if starts[1] == starts[0]:
        starts[1] = (starts[1] + 1) % size
    result: list[dict] = []
    for position in starts:
        item, index, upgrade = rows[position]
        result.append({
            "ref_key": f"writing:{item.get('id')}:{index}",
            "payload": {
                "en": str(upgrade.get("high") or "").strip(),
                "weak": str(upgrade.get("low") or "").strip(),
                "why": str(upgrade.get("why") or "").strip(),
                "context": f"{item.get('title') or '写作'} · {item.get('type') or ''}",
                "source_id": f"{item.get('id')}#{index}",
            },
        })
    return result


def _translation_payloads(day: str) -> list[dict]:
    items = train_content.library()["translation"]
    if not items:
        return []
    item = items[_ordinal(day) % len(items)]
    terms = [term for term in item.get("terms") or [] if isinstance(term, dict)]
    if not terms:
        return []
    size = min(TERMS_PER_DAY, len(terms))
    start = (_ordinal(day) * TERMS_PER_DAY) % len(terms)
    result: list[dict] = []
    for offset in range(size):
        term = terms[(start + offset) % len(terms)]
        result.append({
            "ref_key": f"term:{item.get('id')}:{term.get('zh') or ''}",
            "payload": {
                "zh": str(term.get("zh") or "").strip(),
                "en": str(term.get("en") or "").strip(),
                "note": str(term.get("note") or "").strip(),
                "theme": str(item.get("theme") or "").strip(),
                "source_id": f"{item.get('id')}:{term.get('zh') or ''}",
            },
        })
    return result


def _pron_payloads(conn, day: str) -> list[dict]:
    cet6_pron.ensure_pool(conn)
    since = (dt.date.fromisoformat(day) - dt.timedelta(days=PRON_GAP_DAYS)).isoformat()
    candidates = store.pron_candidates(conn, since=since, limit=PRON_PER_DAY)
    result: list[dict] = []
    for item in candidates:
        payload = cet6_pron.payload(conn, item)
        result.append({
            "ref_key": f"pron:{item['id']}",
            "payload": payload,
            "pron_id": item["id"],
        })
    return result


def ensure_day(conn, day: str | None = None) -> None:
    """只生成今天，且每类只补缺失的部分；历史日期不补。"""
    day = str(day or _today())[:10]
    if day != _today():
        return
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
