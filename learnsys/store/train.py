"""写作/翻译提交记录（`train_submissions`）的 SQL 层。

状态机：draft → reviewing → reviewed / failed；二稿新建一行，`parent_id` 指初稿。
批改结果本体在 `service_results`，这里只存摘要与 `result_id`。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now

STATUSES = ("draft", "reviewing", "reviewed", "failed")
COLUMNS = (
    "id", "kind", "prompt_id", "content_version", "mode", "parent_id", "text",
    "word_count", "duration_s", "status", "band", "band_json", "error_count",
    "serious_count", "result_id", "external_score", "flags_json",
    "created_at", "updated_at",
)
_SELECT = ", ".join(COLUMNS)
_EDITABLE = {
    "text", "word_count", "duration_s", "status", "band", "band_json",
    "error_count", "serious_count", "result_id", "external_score",
    "flags_json", "mode",
}


def _row(row) -> dict | None:
    if row is None:
        return None
    item = dict(zip(COLUMNS, row))
    try:
        item["flags"] = json.loads(item.pop("flags_json") or "{}")
    except Exception:  # noqa: BLE001 - 坏 JSON 不能让整行读不出来
        item["flags"] = {}
    return item


def create_submission(conn: sqlite3.Connection, *, kind: str, prompt_id: str,
           content_version: str = "", mode: str = "practice",
           parent_id: int = 0, text: str = "", word_count: int = 0,
           duration_s: int = 0, flags: dict | None = None) -> int:
    stamp = now()
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO train_submissions "
            "(kind, prompt_id, content_version, mode, parent_id, text, word_count, "
            " duration_s, status, flags_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (str(kind), str(prompt_id), str(content_version), str(mode),
             int(parent_id or 0), str(text or ""), int(word_count or 0),
             int(duration_s or 0),
             json.dumps(flags or {}, ensure_ascii=False), stamp, stamp))
        conn.commit()
        return int(cur.lastrowid or 0)


def get_submission(conn: sqlite3.Connection, submission_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_SELECT} FROM train_submissions WHERE id = ?",
        (int(submission_id),)).fetchone()
    return _row(row)


def update_submission(conn: sqlite3.Connection, submission_id: int, **fields) -> bool:
    """只允许编辑白名单字段；返回是否命中一行。"""
    changes = {key: value for key, value in fields.items() if key in _EDITABLE}
    if not changes:
        return False
    changes["updated_at"] = now()
    columns = ", ".join(f"{key} = ?" for key in changes)
    args = list(changes.values()) + [int(submission_id)]
    with _LOCK:
        cur = conn.execute(
            f"UPDATE train_submissions SET {columns} WHERE id = ?", args)
        conn.commit()
        return cur.rowcount > 0


def set_submission_review(conn: sqlite3.Connection, submission_id: int, *, band,
               review: dict, result_id: int) -> bool:
    errors = review.get("errors") or []
    serious = sum(1 for row in errors if row.get("severity") == "严重")
    return update_submission(
        conn, submission_id, status="reviewed", band=band,
        band_json=json.dumps(review, ensure_ascii=False),
        error_count=len(errors), serious_count=serious,
        result_id=int(result_id or 0))


def list_submissions(conn: sqlite3.Connection, *, kind: str = "", status: str = "",
              prompt_id: str = "", mode: str = "", exclude_mode: str = "",
              limit: int = 50, offset: int = 0) -> dict:
    where = ["1 = 1"]
    args: list = []
    if kind:
        where.append("kind = ?")
        args.append(str(kind))
    if status:
        where.append("status = ?")
        args.append(str(status))
    if prompt_id:
        where.append("prompt_id = ?")
        args.append(str(prompt_id))
    if mode:
        where.append("mode = ?")
        args.append(str(mode))
    if exclude_mode:
        where.append("mode <> ?")
        args.append(str(exclude_mode))
    clause = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM train_submissions WHERE {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT {_SELECT} FROM train_submissions WHERE {clause} "
        "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
        args + [max(1, min(500, int(limit))), max(0, int(offset))]).fetchall()
    return {"items": [_row(row) for row in rows], "count": int(total)}


def latest_train_by_prompt(conn: sqlite3.Connection, kind: str) -> dict:
    """每个题目的最近一次已批改记录：列表页显示完成次数与最近档位。"""
    rows = conn.execute(
        "SELECT prompt_id, band FROM train_submissions "
        "WHERE kind = ? AND status = 'reviewed' "
        "ORDER BY updated_at DESC, id DESC", (str(kind),)).fetchall()
    out: dict[str, dict] = {}
    for prompt_id, band in rows:
        entry = out.setdefault(str(prompt_id), {"done": 0, "last_band": None})
        entry["done"] += 1
        if entry["last_band"] is None:
            entry["last_band"] = band
    return out


def reviewed_rows(conn: sqlite3.Connection, *, since: str = "") -> list[dict]:
    """已批改的提交（统计与趋势的唯一读取点）；按批改时间升序。"""
    where = ["status = 'reviewed'"]
    args: list = []
    if since:
        where.append("substr(COALESCE(updated_at, created_at), 1, 10) >= ?")
        args.append(str(since)[:10])
    columns = ("id, kind, prompt_id, mode, band, band_json, word_count, "
               "serious_count, error_count, duration_s, created_at, updated_at")
    rows = conn.execute(
        f"SELECT {columns} FROM train_submissions WHERE {' AND '.join(where)} "
        "ORDER BY updated_at ASC, id ASC", args).fetchall()
    keys = [name.strip() for name in columns.split(",")]
    return [dict(zip(keys, row)) for row in rows]


def activity_counts(conn: sqlite3.Connection, day: str) -> dict:
    """某天完成的训练量（按提交记录算，不依赖事件表）。"""
    counts = {"writing": 0, "translation": 0, "sentence": 0, "minutes": 0.0}
    rows = conn.execute(
        "SELECT kind, mode, COUNT(*), COALESCE(SUM(duration_s), 0) "
        "FROM train_submissions WHERE status IN ('reviewed', 'failed') "
        "AND substr(updated_at, 1, 10) = ? GROUP BY kind, mode",
        (str(day)[:10],)).fetchall()
    for kind, mode, count, seconds in rows:
        count = int(count or 0)
        if mode == "sentence":
            counts["sentence"] += count
        elif kind in ("writing", "translation"):
            counts[kind] += count
            counts["minutes"] += float(seconds or 0) / 60.0
    counts["minutes"] = round(counts["minutes"], 1)
    return counts


def sentence_attempted(conn: sqlite3.Connection, *,
                       status: str = "reviewed") -> list[str]:
    """已练过的单句 id（一句一译的队列靠它去重，跨刷新也算）。"""
    sql = "SELECT DISTINCT prompt_id FROM train_submissions WHERE mode = 'sentence'"
    args: list = []
    if status:
        sql += " AND status = ?"
        args.append(str(status))
    return [str(row[0]) for row in conn.execute(sql, args).fetchall()]


def delete_submission(conn: sqlite3.Connection, submission_id: int) -> bool:
    with _LOCK:
        cur = conn.execute(
            "DELETE FROM train_submissions WHERE id = ?", (int(submission_id),))
        conn.commit()
        return cur.rowcount > 0
