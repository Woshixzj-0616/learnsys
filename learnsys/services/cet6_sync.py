"""六级双写审计：写前比对 → 写入 → 写后校验。

判据与口径见 `docs/施工单/P17.1-六级双写退休.md`。

要点：
- 「无差异」指打开试卷这一刻，本地整卷快照与服务端 `cet6_progress` 一致；
  不是推送后自己跟自己比（那样天然相等，是假证据）。
- 空快照保护：本地 4 个同步字段全空、服务端有内容时拒绝写入，避免清缓存后把进度清零。
- 写后校验只证明写成功，不参与「无差异」判据。
"""
from __future__ import annotations

import sqlite3

from learnsys import store

NOTE_LIMIT = 1000
DIFF_LIMIT = 50
SYNC_FIELDS = ("done", "tags", "note", "loops", "plays")


def _fingerprint(row: dict) -> tuple:
    return (row.get("section") or "", row.get("item") or "", int(row.get("sentence") or 0))


def _tags(value) -> list[str]:
    if isinstance(value, str):
        value = value.split("、")
    return sorted({str(x).strip() for x in (value or []) if str(x).strip()})


def _note(value) -> str:
    return str(value or "")[:NOTE_LIMIT]


def canonical_rows(items: list[dict]) -> list[dict]:
    """把多段请求摊平成按 `(section,item,sentence)` 定位的行。"""
    rows: list[dict] = []
    for it in items or []:
        section = str(it.get("section") or "")
        title = str(it.get("item") or "")
        done_set = {int(x) for x in (it.get("done") or [])}
        for sent in it.get("sentences") or []:
            try:
                number = int(sent.get("sentence"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "section": section,
                "item": title,
                "sentence": number,
                "done": number in done_set,
                "tags": _tags(sent.get("tags")),
                "note": _note(sent.get("note")),
                "loops": max(0, int(sent.get("loops") or 0)),
                "plays": max(0, int(sent.get("plays") or 0)),
            })
    return rows


def _meaningful(row: dict) -> bool:
    return bool(row.get("done") or row.get("tags") or row.get("note")
                or int(row.get("loops") or 0) > 0)


def _value(field: str, row: dict):
    if field == "tags":
        return sorted(row.get("tags") or [])
    if field == "note":
        return str(row.get("note") or "")[:NOTE_LIMIT]
    if field in ("loops", "plays"):
        return int(row.get(field) or 0)
    return bool(row.get("done"))


def compare_rows(local_rows: list[dict], server_rows: list[dict],
                 skipped: set[tuple[str, str]] | None = None) -> dict:
    """逐行逐字段比对；返回计数与差异明细（最多 50 条）。"""
    skipped = skipped or set()
    local = {_fingerprint(r): r for r in local_rows}
    server = {_fingerprint(r): r for r in server_rows}
    diffs: list[dict] = []
    diff_fields = minor_fields = diff_rows = 0
    missing_db = orphan_db = orphan_blocking = 0

    # 只有「有意义」的行才算缺失/孤儿：新试卷首次打开会有一堆全零行，
    # 它们没学过、不是差异，不能因此把第一天判成脏。
    for key in local.keys() - server.keys():
        if not _meaningful(local[key]):
            continue
        missing_db += 1
        diff_rows += 1
        diffs.append({"section": key[0], "item": key[1], "sentence": key[2],
                      "field": "presence", "kind": "missing_db",
                      "local_value": "有", "server_value": "无"})
    for key in server.keys() - local.keys():
        if not _meaningful(server[key]):
            continue
        where = "orphan_blocking" if (key[0], key[1]) in skipped else "orphan_db"
        if where == "orphan_blocking":
            orphan_blocking += 1
        else:
            orphan_db += 1
        diff_rows += 1
        diffs.append({"section": key[0], "item": key[1], "sentence": key[2],
                      "field": "presence", "kind": where,
                      "local_value": "无", "server_value": "有"})

    for key in local.keys() & server.keys():
        a, b = local[key], server[key]
        hit = False
        for field in SYNC_FIELDS:
            va, vb = _value(field, a), _value(field, b)
            if va == vb:
                continue
            hit = True
            if field == "plays" and abs(int(va) - int(vb)) <= 2:
                minor_fields += 1
                continue
            diff_fields += 1
            diffs.append({"section": key[0], "item": key[1], "sentence": key[2],
                          "field": field, "kind": "value",
                          "local_value": va, "server_value": vb})
        if hit:
            diff_rows += 1

    return {"compared": len(local.keys() | server.keys()),
            "diff_fields": diff_fields, "diff_rows": diff_rows,
            "minor_fields": minor_fields, "missing_db": missing_db,
            "orphan_db": orphan_db, "orphan_blocking": orphan_blocking,
            "diffs": diffs[:DIFF_LIMIT]}


def _server_rows(conn: sqlite3.Connection, paper_id: str) -> list[dict]:
    return store.cet6_progress_paper_rows(conn, paper_id)


def _post_ok(conn: sqlite3.Connection, paper_id: str, rows: list[dict]) -> bool:
    """写后校验：每个本地行都能在库里按原值读回。"""
    server = {_fingerprint(r): r for r in _server_rows(conn, paper_id)}
    for row in rows:
        got = server.get(_fingerprint(row))
        if got is None:
            return False
        for field in SYNC_FIELDS:
            if _value(field, row) != _value(field, got):
                return False
    return True


def _invalid_rows(rows: list[dict], raw_items: list[dict]) -> int:
    """note 超长（会被截断）或句子号非法的行数。"""
    invalid = 0
    for it in raw_items or []:
        for sent in it.get("sentences") or []:
            if len(str(sent.get("note") or "")) > NOTE_LIMIT:
                invalid += 1
            try:
                if int(sent.get("sentence")) <= 0:
                    invalid += 1
            except (TypeError, ValueError):
                invalid += 1
    return invalid


def audit_and_write(conn: sqlite3.Connection, *, paper_id: str, paper_title: str,
                    items: list[dict], hydration: str = "local", mode: str = "http",
                    paper_sig: str = "", client_ts: str = "", client_day: str = "",
                    push_failed: int = 0, skipped: set[tuple[str, str]] | None = None,
                    skipped_items: list[dict] | None = None) -> dict:
    """一次整卷审计：比对、保护、写入、校验、落 run/diffs。"""
    skipped = skipped or {(str(s.get("section") or ""), str(s.get("item") or ""))
                          for s in (skipped_items or [])}
    write_items = [it for it in (items or [])
                   if (str(it.get("section") or ""), str(it.get("item") or "")) not in skipped]
    rows = canonical_rows(write_items)
    server = _server_rows(conn, paper_id)
    invalid = _invalid_rows(rows, items)

    pre_meaningful = any(_meaningful(r) for r in server)
    incoming_meaningful = any(_meaningful(r) for r in rows)
    stamp = store.now()
    day = stamp[:10]
    base = dict(ts=stamp, day=day, client_ts=client_ts, client_day=client_day,
                paper_id=paper_id, paper_title=paper_title, mode=mode,
                hydration=hydration, paper_sig=paper_sig, items=len(write_items),
                sentences=len(rows), invalid=invalid)

    if incoming_meaningful == 0 and pre_meaningful:
        run_id = store.add_cet6_dualwrite_run(
            conn, **base, compared=0, status="blocked_empty",
            error="本地快照为空、服务端有进度；已拒绝写入，请先从服务端恢复。")
        return {"ok": False, "status": "blocked_empty", "run_id": run_id,
                "compared": 0, "diff_fields": 0, "minor_fields": 0,
                "missing_db": 0, "orphan_db": 0, "orphan_blocking": 0,
                "invalid": invalid, "post_ok": 0,
                "message": "本地快照为空，已拒绝写入以保护服务端进度。"}

    result = compare_rows(rows, server, skipped)
    try:
        for it in write_items:
            section = str(it.get("section") or "")
            title = str(it.get("item") or "")
            store.upsert_cet6_progress(
                conn, paper_id=paper_id, paper_title=paper_title,
                section=section, item=title,
                rows=it.get("sentences") or [], done=it.get("done") or [])
        post_ok = _post_ok(conn, paper_id, rows)
    except Exception as exc:                     # 记流水后再抛给路由
        store.add_cet6_dualwrite_run(
            conn, **base, **{k: result[k] for k in
                             ("compared", "diff_fields", "diff_rows", "minor_fields",
                              "missing_db", "orphan_db", "orphan_blocking")},
            post_ok=0, status="error", error=str(exc)[:500])
        raise

    status = "ok"
    if (result["diff_fields"] or result["missing_db"] or result["orphan_db"]
            or result["orphan_blocking"] or invalid or not post_ok):
        status = "diff"
    elif result["minor_fields"]:
        status = "ok_minor"
    if push_failed:
        result.setdefault("diffs", []).append(
            {"section": "", "item": "", "sentence": 0, "field": "push",
             "kind": "push_failed", "local_value": f"失败 {int(push_failed)} 次",
             "server_value": ""})
        status = "diff"

    run_id = store.add_cet6_dualwrite_run(
        conn, **base, compared=result["compared"],
        diff_fields=result["diff_fields"], diff_rows=result["diff_rows"],
        minor_fields=result["minor_fields"], missing_db=result["missing_db"],
        orphan_db=result["orphan_db"], orphan_blocking=result["orphan_blocking"],
        post_ok=1 if post_ok else 0, status=status,
        error="" if status in ("ok", "ok_minor") else "存在差异，见明细。")
    store.add_cet6_dualwrite_diffs(conn, run_id, paper_id, result["diffs"])
    return {"ok": status in ("ok", "ok_minor", "diff"), "status": status,
            "run_id": run_id, "compared": result["compared"],
            "diff_fields": result["diff_fields"], "minor_fields": result["minor_fields"],
            "missing_db": result["missing_db"], "orphan_db": result["orphan_db"],
            "orphan_blocking": result["orphan_blocking"], "invalid": invalid,
            "post_ok": 1 if post_ok else 0}
