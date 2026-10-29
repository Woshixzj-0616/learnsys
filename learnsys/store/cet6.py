"""六级精听逐句进度：localStorage 仍是第一现场，这里是服务端镜像。"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from learnsys.core import db as core_db
from ._base import _LOCK, now


# ---- 六级精听：逐句进度（P12） ----
# localStorage 仍是工作台的第一现场；这里是服务端镜像，用来跨设备/跨页取上下文。
# `done=None` = 不碰完成状态；`done=[...]` = 这次提交就是该段的完整完成状态。

def upsert_cet6_progress(conn: sqlite3.Connection, *, paper_id: str,
                         paper_title: str = "", section: str, item: str,
                         rows: list[dict], done: list[int] | None = None) -> int:
    """写入某段的逐句进度；返回处理的句子数。

    句子按 `(paper_id, section, item, sentence)` upsert。`tags` 可以是列表或
    已经拼好的字符串；`done` 不传时保留库里原值。
    """
    stamp = now()
    done_set = {int(x) for x in (done or [])}
    count = 0
    with _LOCK:
        for row in rows or []:
            try:
                sentence = int(row.get("sentence"))
            except (TypeError, ValueError):
                continue
            tags = row.get("tags") or ""
            if isinstance(tags, (list, tuple, set)):
                tags = "、".join(str(t) for t in tags if str(t).strip())
            note = str(row.get("note") or "")[:1000]
            en = str(row.get("en") or "")[:4000]
            try:
                loops = max(0, int(row.get("loops") or 0))
                plays = max(0, int(row.get("plays") or 0))
            except (TypeError, ValueError):
                loops = plays = 0
            if done is None:
                conn.execute(
                    "INSERT INTO cet6_progress "
                    "(paper_id, paper_title, section, item, sentence, en, tags, note, "
                    " loops, plays, done, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?) "
                    "ON CONFLICT(paper_id, section, item, sentence) DO UPDATE SET "
                    "paper_title=excluded.paper_title, en=excluded.en, tags=excluded.tags, "
                    "note=excluded.note, loops=excluded.loops, plays=excluded.plays, "
                    "updated_at=excluded.updated_at",
                    (paper_id, paper_title, section, item, sentence, en, tags, note,
                     loops, plays, stamp))
            else:
                conn.execute(
                    "INSERT INTO cet6_progress "
                    "(paper_id, paper_title, section, item, sentence, en, tags, note, "
                    " loops, plays, done, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(paper_id, section, item, sentence) DO UPDATE SET "
                    "paper_title=excluded.paper_title, en=excluded.en, tags=excluded.tags, "
                    "note=excluded.note, loops=excluded.loops, plays=excluded.plays, "
                    "done=excluded.done, updated_at=excluded.updated_at",
                    (paper_id, paper_title, section, item, sentence, en, tags, note,
                     loops, plays, 1 if sentence in done_set else 0, stamp))
            count += 1
        conn.commit()
    return count


def cet6_progress_item(conn: sqlite3.Connection, *, paper_id: str,
                       section: str, item: str) -> list[dict]:
    """某段的逐句进度；tags 还原成列表，按句号升序。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT sentence, en, tags, note, loops, plays, done, updated_at "
            "FROM cet6_progress WHERE paper_id = ? AND section = ? AND item = ? "
            "ORDER BY sentence", (paper_id, section, item)).fetchall()
    return [
        {"sentence": int(row[0]), "en": row[1] or "",
         "tags": [x for x in str(row[2] or "").split("、") if x],
         "note": row[3] or "", "loops": int(row[4] or 0),
         "plays": int(row[5] or 0), "done": bool(row[6]),
         "updated_at": row[7] or ""}
        for row in rows
    ]


def cet6_progress_paper_rows(conn: sqlite3.Connection, paper_id: str) -> list[dict]:
    """整卷逐句进度（双写审计用）；tags 还原成列表，按段、句号排序。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT paper_title, section, item, sentence, en, tags, note, loops, plays, done "
            "FROM cet6_progress WHERE paper_id = ? ORDER BY section, item, sentence",
            (paper_id,)).fetchall()
    return [
        {"paper_title": row[0] or "", "section": row[1], "item": row[2],
         "sentence": int(row[3]), "en": row[4] or "",
         "tags": [x for x in str(row[5] or "").split("、") if x],
         "note": row[6] or "", "loops": int(row[7] or 0),
         "plays": int(row[8] or 0), "done": bool(row[9])}
        for row in rows
    ]


def add_cet6_dualwrite_run(conn: sqlite3.Connection, **fields) -> int:
    """记一次整卷审计；返回 run id。字段缺省走表默认值。"""
    columns = [
        "ts", "day", "client_ts", "client_day", "paper_id", "paper_title",
        "mode", "hydration", "paper_sig", "items", "sentences", "compared",
        "diff_fields", "diff_rows", "minor_fields", "missing_db", "orphan_db",
        "orphan_blocking", "invalid", "post_ok", "status", "error",
    ]
    int_fields = {"items", "sentences", "compared", "diff_fields", "diff_rows",
                  "minor_fields", "missing_db", "orphan_db", "orphan_blocking",
                  "invalid", "post_ok"}
    values = [int(fields.get(name, 0) or 0) if name in int_fields
              else str(fields.get(name, "") or "") for name in columns]
    with _LOCK:
        cur = conn.execute(
            f"INSERT INTO cet6_dualwrite_runs ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})", values)
        conn.commit()
        return int(cur.lastrowid)


def add_cet6_dualwrite_diffs(conn: sqlite3.Connection, run_id: int, paper_id: str,
                             diffs: list[dict]) -> None:
    """记差异明细；只存前 50 条，长值截 200 字。"""
    stamp = now()
    with _LOCK:
        for item in (diffs or [])[:50]:
            conn.execute(
                "INSERT INTO cet6_dualwrite_diffs "
                "(run_id, ts, paper_id, section, item, sentence, field, kind, "
                " local_value, server_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, stamp, paper_id, str(item.get("section") or "")[:200],
                 str(item.get("item") or "")[:200], int(item.get("sentence") or 0),
                 str(item.get("field") or "")[:40], str(item.get("kind") or "value")[:40],
                 str(item.get("local_value") or "")[:200],
                 str(item.get("server_value") or "")[:200]))
        conn.commit()


def cet6_progress_summary(conn: sqlite3.Connection, paper_id: str = "") -> list[dict]:
    """按试卷汇总：总句数、已完成、断点数、最后更新时间。"""
    where, args = "", []
    if paper_id:
        where = "WHERE paper_id = ?"
        args.append(paper_id)
    with _LOCK:
        rows = conn.execute(
            "SELECT paper_id, MAX(paper_title), COUNT(*), SUM(done), "
            "SUM(CASE WHEN tags <> '' THEN 1 ELSE 0 END), MAX(updated_at) "
            f"FROM cet6_progress {where} GROUP BY paper_id "
            "ORDER BY MAX(updated_at) DESC", args).fetchall()
    return [
        {"paper_id": row[0], "paper": row[1] or "", "sentences": int(row[2] or 0),
         "done": int(row[3] or 0), "breakpoints": int(row[4] or 0),
         "last": row[5] or ""}
        for row in rows
    ]


def cet6_recent_events(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT ts, paper_id, paper_title, section, item, sentence, tags, note, "
            "loops, plays FROM cet6_events ORDER BY ts DESC, id DESC LIMIT ?",
            (max(1, min(int(limit or 20), 100)),)).fetchall()
    return [
        {"ts": row[0] or "", "paper_id": row[1] or "", "paper": row[2] or "",
         "section": row[3] or "", "item": row[4] or "", "sentence": row[5],
         "tags": [x for x in str(row[6] or "").split("、") if x],
         "note": row[7] or "", "loops": int(row[8] or 0), "plays": int(row[9] or 0)}
        for row in rows
    ]


def latest_progress_item(conn: sqlite3.Connection) -> dict | None:
    """最近更新过的一段进度（没给 paper 时，上下文接口用它兜底）。"""
    with _LOCK:
        row = conn.execute(
            "SELECT paper_id, paper_title, section, item FROM cet6_progress "
            "ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {"paper_id": row[0], "paper": row[1] or "", "section": row[2], "item": row[3]}


def progress_paper_title(conn: sqlite3.Connection, paper_id: str) -> str:
    with _LOCK:
        row = conn.execute(
            "SELECT MAX(paper_title) FROM cet6_progress WHERE paper_id = ?",
            (str(paper_id),)).fetchone()
    return str(row[0] or "") if row and row[0] else ""


def cet6_summary(conn: sqlite3.Connection) -> list[dict]:
    """按卷聚合的断点数 / Section 数 / 最近时间（上下文页兜底）。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT paper_title, COUNT(*), COUNT(DISTINCT section), MAX(ts) "
            "FROM cet6_events GROUP BY paper_title ORDER BY MAX(ts) DESC").fetchall()
    return [{"paper": row[0] or "", "breakpoints": int(row[1] or 0),
             "sections": int(row[2] or 0), "last": row[3] or ""}
            for row in rows]


def _dedupe_key(paper_id: str, section: str, item: str, one: dict) -> str:
    payload = json.dumps({
        "paper_id": paper_id, "section": section, "item": item,
        "sentence": one.get("sentence"), "tags": one.get("tags"),
        "note": one.get("note"), "loops": one.get("loops"),
        "plays": one.get("plays"),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def add_breakpoint_events(conn: sqlite3.Connection, *, stamp: str, paper_id: str,
                          paper: str, section: str, item: str,
                          sentences: list[dict], analysis: dict | None = None) -> int:
    """把一段里真正的断点写进 `cet6_events`；返回新增条数。

    逐句进度本身在 `cet6_progress`；时间线只收带标签 / 笔记 / 循环的句子，
    否则每段几十句空记录会把「今日 / 学习点」撑爆。
    """
    count = 0
    index_rows: list[tuple[int, str]] = []
    analysis_json = json.dumps(analysis, ensure_ascii=False) if analysis else ""
    with _LOCK:
        for one in sentences:
            tags = "、".join(one.get("tags") or [])
            note = str(one.get("note") or "")
            loops = int(one.get("loops") or 0)
            plays = int(one.get("plays") or 0)
            if not (tags or note.strip() or loops > 0):
                continue
            key = _dedupe_key(paper_id, section, item, one)
            cur = conn.execute(
                "INSERT OR IGNORE INTO cet6_events "
                "(ts, paper_id, paper_title, section, item, sentence, tags, note, "
                " loops, plays, analysis_json, dedupe_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stamp, paper_id, paper, section, item, int(one.get("sentence") or 0),
                 tags, note, loops, plays, analysis_json, key))
            if cur.rowcount:
                count += 1
                index_rows.append((int(cur.lastrowid),
                                   f"{paper} {section} {item} {one.get('en') or ''} "
                                   f"{note} {tags}"))
            elif analysis_json:
                conn.execute(
                    "UPDATE cet6_events SET analysis_json = ? WHERE dedupe_key = ?",
                    (analysis_json, key))
        if count:
            conn.execute(
                "INSERT INTO events (ts, module, kind, ref_id, title, meta_json) "
                "VALUES (?, 'cet6', 'breakpoint', 0, ?, ?)",
                (stamp, f"{paper} / {section} / {item}",
                 json.dumps({"count": count, "analysis": bool(analysis_json)},
                            ensure_ascii=False)))
        conn.commit()
    for ref_id, body in index_rows:
        core_db.index_row(conn, "cet6", ref_id, stamp, body)
    return count


def _ensure_imports(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cet6_imports "
        "(key TEXT PRIMARY KEY, value TEXT, ts TEXT)")


def save_import_items(conn: sqlite3.Connection, items: dict, stamp: str) -> int:
    """file:// 版工作台送来的 localStorage 快照（P4 迁移桥）。"""
    with _LOCK:
        _ensure_imports(conn)
        for key, value in items.items():
            conn.execute(
                "INSERT INTO cet6_imports (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = excluded.ts",
                (key, value, stamp))
        conn.commit()
    return len(items)


def load_import_items(conn: sqlite3.Connection) -> dict:
    with _LOCK:
        _ensure_imports(conn)
        rows = conn.execute("SELECT key, value FROM cet6_imports").fetchall()
    return {row[0]: row[1] for row in rows}
