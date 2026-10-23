"""六级精听逐句进度：localStorage 仍是第一现场，这里是服务端镜像。"""
from __future__ import annotations

import sqlite3

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
