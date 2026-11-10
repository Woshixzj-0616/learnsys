"""复习调度域：review_state 是唯一状态，review_log 是历史。

错题/生词共用同一套 FSRS 状态；到期队列在 SQL 里直接联两张业务表。
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from ._base import _LOCK, now


def _next_review(ts: str, last_review: str, stage: int) -> str:
    """下次复习日；练完 3 轮（stage=3）后返回空串。"""
    if stage >= len(REVIEW_INTERVALS):
        return ""
    base = str(last_review or ts)[:10]
    try:
        day = dt.date.fromisoformat(base)
    except ValueError:
        return ""
    return (day + dt.timedelta(days=REVIEW_INTERVALS[stage])).isoformat()
def _attach_review_states(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """把 FSRS 状态贴到错题上；没有状态的保留旧 1/3/7 的回退值。"""
    if not items:
        return items
    ids = [item["id"] for item in items]
    placeholders = ",".join("?" * len(ids))
    with _LOCK:
        state_rows = conn.execute(
            "SELECT item_id, due, state, reps, lapses, scheduled_days "
            "FROM review_state WHERE item_type = 'wrong' "
            f"AND item_id IN ({placeholders})", ids).fetchall()
    states = {int(row[0]): row for row in state_rows}
    for item in items:
        state = states.get(item["id"])
        if state:
            item["next_review"] = state[1] or item["next_review"]
            item["review_state"] = state[2] or "new"
            item["review_reps"] = int(state[3] or 0)
            item["review_lapses"] = int(state[4] or 0)
            item["scheduled_days"] = int(state[5] or 0)
    return items
REVIEW_INTERVALS = (1, 3, 7)   # 收录后第 1 / 3 / 7 天各复习一次
# ---------------------------------------------------------------------------
# P14 复习调度：review_state 是唯一状态，review_log 是历史
# ---------------------------------------------------------------------------

REVIEW_ITEM_TYPES = ("wrong", "vocab", "accum")

# 每日积累从这一天起产卡；历史 120 条不回填（P34.2 阶段 5 口径）。
DAILY_REVIEW_EPOCH = dt.date(2026, 11, 7)
ACCUM_REVIEW_KINDS = ("writing", "translation")
_REVIEW_STATE_COLUMNS = (
    "item_type", "item_id", "state", "due", "stability", "difficulty",
    "reps", "lapses", "last_review", "scheduled_days", "elapsed_days",
    "updated_at",
)
_REVIEW_STATE_SELECT = ", ".join(_REVIEW_STATE_COLUMNS)


def _review_state_dict(row) -> dict:
    out = dict(zip(_REVIEW_STATE_COLUMNS, row))
    out["item_id"] = int(out.get("item_id") or 0)
    for key in ("reps", "lapses", "scheduled_days", "elapsed_days"):
        out[key] = int(out.get(key) or 0)
    for key in ("stability", "difficulty"):
        out[key] = float(out.get(key) or 0)
    return out


def get_review_state(conn: sqlite3.Connection, item_type: str,
                     item_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_REVIEW_STATE_SELECT} FROM review_state "
        "WHERE item_type = ? AND item_id = ?", (item_type, int(item_id))).fetchone()
    return _review_state_dict(row) if row else None


def save_review_state(conn: sqlite3.Connection, item_type: str, item_id: int,
                      *, state: str, due: str, stability: float = 0,
                      difficulty: float = 0, reps: int = 0, lapses: int = 0,
                      last_review: str = "", scheduled_days: int = 0,
                      elapsed_days: int = 0) -> dict:
    stamp = now()
    with _LOCK:
        conn.execute(
            "INSERT INTO review_state "
            "(item_type, item_id, state, due, stability, difficulty, reps, lapses, "
            " last_review, scheduled_days, elapsed_days, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(item_type, item_id) DO UPDATE SET "
            "state=excluded.state, due=excluded.due, stability=excluded.stability, "
            "difficulty=excluded.difficulty, reps=excluded.reps, "
            "lapses=excluded.lapses, last_review=excluded.last_review, "
            "scheduled_days=excluded.scheduled_days, "
            "elapsed_days=excluded.elapsed_days, updated_at=excluded.updated_at",
            (item_type, int(item_id), state, due, float(stability or 0),
             float(difficulty or 0), int(reps or 0), int(lapses or 0),
             last_review or "", int(scheduled_days or 0), int(elapsed_days or 0),
             stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_REVIEW_STATE_SELECT} FROM review_state "
            "WHERE item_type = ? AND item_id = ?", (item_type, int(item_id))).fetchone()
    return _review_state_dict(row)


def add_review_log(conn: sqlite3.Connection, *, item_type: str, item_id: int,
                   rating: int, state_before: str = "", due_before: str = "",
                   due_after: str = "", stability: float = 0,
                   difficulty: float = 0, elapsed_days: int = 0,
                   scheduled_days: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO review_log "
            "(ts, item_type, item_id, rating, state_before, due_before, due_after, "
            " stability, difficulty, elapsed_days, scheduled_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), item_type, int(item_id), int(rating), state_before or "",
             due_before or "", due_after or "", float(stability or 0),
             float(difficulty or 0), int(elapsed_days or 0),
             int(scheduled_days or 0)))
        conn.commit()
        return int(cur.lastrowid or 0)


def seed_review_states(conn: sqlite3.Connection, today=None) -> int:
    """把旧 1/3/7 错题转成 FSRS 初始状态；幂等。"""
    day = str(today or dt.date.today().isoformat())[:10]
    rows = conn.execute(
        "SELECT w.id, w.ts, w.review_stage, w.last_review, w.mastered "
        "FROM wrong_items w LEFT JOIN review_state r "
        "ON r.item_type = 'wrong' AND r.item_id = w.id "
        "WHERE r.item_id IS NULL").fetchall()
    seeded = 0
    for row in rows:
        item_id, ts, stage, last_review, mastered = row
        if mastered:
            continue
        stage = int(stage or 0)
        # 新收的错题明天再出现，别在刚答错时立刻催复习（沿用旧版行为）
        due = _next_review(ts, last_review or "", stage) or day
        stability = max(1.0, float(REVIEW_INTERVALS[stage - 1])) if stage else 1.0
        save_review_state(
            conn, "wrong", int(item_id),
            state="new" if stage == 0 else "review", due=due,
            stability=stability, difficulty=5.0, reps=stage, lapses=0,
            last_review=str(last_review or ""),
            scheduled_days=int(stability) if stage else 0, elapsed_days=0)
        seeded += 1
    vocab_rows = conn.execute(
        "SELECT v.id FROM vocab_items v LEFT JOIN review_state r "
        "ON r.item_type = 'vocab' AND r.item_id = v.id "
        "WHERE r.item_id IS NULL AND v.status = 'active'").fetchall()
    for (item_id,) in vocab_rows:
        save_review_state(
            conn, "vocab", int(item_id), state="new", due=day, stability=1.0,
            difficulty=5.0, reps=0, lapses=0, last_review="",
            scheduled_days=0, elapsed_days=0)
        seeded += 1
    # 每日积累：只收启用日之后的写作句型与翻译短语，历史条目不回填。
    accum_rows = conn.execute(
        "SELECT a.id, a.day FROM cet6_accum_items a LEFT JOIN review_state r "
        "ON r.item_type = 'accum' AND r.item_id = a.id "
        "WHERE r.item_id IS NULL AND a.day >= ? AND a.kind IN (?, ?)",
        (DAILY_REVIEW_EPOCH.isoformat(), *ACCUM_REVIEW_KINDS)).fetchall()
    for item_id, item_day in accum_rows:
        due = max(str(item_day or day)[:10], day)
        save_review_state(
            conn, "accum", int(item_id), state="new", due=due, stability=1.0,
            difficulty=5.0, reps=0, lapses=0, last_review="",
            scheduled_days=0, elapsed_days=0)
        seeded += 1
    return seeded


def _review_join_sql() -> str:
    return (
        "SELECT r.item_type, r.item_id, r.state, r.due, r.stability, r.difficulty, "
        "r.reps, r.lapses, r.last_review, r.scheduled_days, "
        "w.question, w.answer, w.my_answer, w.tags, w.note, w.material_id, w.source, "
        "v.word, v.meaning, v.context, v.paper_title, v.source, "
        "a.kind, a.payload_json "
        "FROM review_state r "
        "LEFT JOIN wrong_items w ON r.item_type = 'wrong' AND w.id = r.item_id "
        "LEFT JOIN vocab_items v ON r.item_type = 'vocab' AND v.id = r.item_id "
        "LEFT JOIN cet6_accum_items a ON r.item_type = 'accum' AND a.id = r.item_id ")


def _review_card(row) -> dict:
    item = {
        "item_type": row[0], "item_id": int(row[1]), "state": row[2],
        "due": row[3] or "", "stability": float(row[4] or 0),
        "difficulty": float(row[5] or 0), "reps": int(row[6] or 0),
        "lapses": int(row[7] or 0), "last_review": row[8] or "",
        "scheduled_days": int(row[9] or 0),
        "question": row[10] or "", "answer": row[11] or "",
        "my_answer": row[12] or "", "tags": row[13] or "", "note": row[14] or "",
        "material_id": int(row[15] or 0),
        "source": row[16] or row[21] or "",
        "word": row[17] or "", "meaning": row[18] or "",
        "context": row[19] or "", "paper_title": row[20] or "",
    }
    if item["item_type"] == "accum":
        _fill_accum_card(item, row[22] or "", row[23] or "")
    item["title"] = (item["question"]
                     if item["item_type"] == "wrong"
                     or (item["item_type"] == "accum"
                         and item.get("accum_kind") == "writing")
                     else item["word"])
    return item


def _fill_accum_card(item: dict, kind: str, raw_payload: str) -> None:
    """把每日积累的 payload 映射成现有卡片字段，前端不用再学一套结构。

    写作句型走句子 tab：正面是中文用途，背面是句型 + 例句；
    翻译短语走词 tab：正面是中文短语，背面是英文表达 + 提示。
    """
    try:
        payload = json.loads(raw_payload or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    item["accum_kind"] = kind or ""
    item["source"] = "daily"
    item["tags"] = ""
    if kind == "writing":
        pattern = str(payload.get("pattern") or "").strip()
        item["question"] = str(payload.get("zh") or "").strip()
        item["answer"] = pattern       # 兼容旧前端 / MCP
        item["pattern"] = pattern
        item["example"] = str(payload.get("example") or "").strip()
        item["example_zh"] = str(payload.get("example_zh") or "").strip()
        item["note"] = str(payload.get("note") or "").strip()   # 只放语法提示
        item["tags"] = str(payload.get("group") or "").strip()
        item["my_answer"] = ""
    else:
        item["word"] = str(payload.get("zh") or "").strip()
        item["meaning"] = str(payload.get("en") or "").strip()
        item["context"] = str(payload.get("note") or payload.get("theme") or "").strip()


def _review_where(day: str, item_types: tuple, sources: tuple,
                  accum_kinds: tuple = ()) -> tuple[str, list]:
    """到期卡的公共条件：卡片仍有效，且属于给定类型/来源。"""
    where = [
        "r.due <= ?",
        "(r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0))",
        "(r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active'))",
        "(r.item_type <> 'accum' OR a.id IS NOT NULL)",
    ]
    args: list = [day]
    types = tuple(t for t in item_types if t in REVIEW_ITEM_TYPES)
    if types:
        where.append("r.item_type IN (" + ",".join("?" * len(types)) + ")")
        args.extend(types)
    src = tuple(s for s in sources if s)
    if src:
        where.append("(r.item_type <> 'wrong' OR w.source IN ("
                     + ",".join("?" * len(src)) + "))")
        args.extend(src)
    kinds = tuple(k for k in accum_kinds if k)
    if kinds:
        where.append("(r.item_type <> 'accum' OR a.kind IN ("
                     + ",".join("?" * len(kinds)) + "))")
        args.extend(kinds)
    return " AND ".join(where), args


def due_review_items(conn: sqlite3.Connection, *, limit: int = 50,
                     today=None, item_type: str = "",
                     item_types: tuple = (), sources: tuple = (),
                     accum_kinds: tuple = (),
                     max_new: int | None = None) -> list[dict]:
    """到期卡队列。

    `item_types` / `sources` 是英语复习的过滤条件；`max_new` 限制新卡张数
    （英语复习每天 10 张），不会影响已进入复习的卡。
    """
    day = str(today or dt.date.today().isoformat())[:10]
    types = (item_type,) if item_type in REVIEW_ITEM_TYPES else tuple(item_types)
    where, args = _review_where(day, types, sources, accum_kinds)
    # 多取一些，给新卡限流留出替换空间；最终仍按 due 顺序返回。
    fetch = max(1, min(int(limit or 50), 500))
    # 每日积累当天生成，排在同一轮的最前面；旧错题/生词按到期日排在后面。
    sql = (_review_join_sql() + "WHERE " + where
           + " ORDER BY CASE WHEN r.item_type = 'accum' THEN 0 ELSE 1 END, "
             "r.due, r.item_type, r.item_id LIMIT ?")
    args.append(fetch if max_new is None else min(fetch * 4, 500))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    items = [_review_card(row) for row in rows]
    if max_new is not None:
        left = max(0, int(max_new))
        kept: list[dict] = []
        for item in items:
            if item["state"] == "new" and item["item_type"] != "accum":
                if left <= 0:
                    continue
                left -= 1
            kept.append(item)
        items = kept
    return items[:fetch]


def due_review_count(conn: sqlite3.Connection, *, today=None,
                     item_type: str = "", item_types: tuple = (),
                     sources: tuple = (), accum_kinds: tuple = ()) -> int:
    """只数到期卡张数，不建队列、不碰复习状态（今日页用）。"""
    day = str(today or dt.date.today().isoformat())[:10]
    types = (item_type,) if item_type in REVIEW_ITEM_TYPES else tuple(item_types)
    where, args = _review_where(day, types, sources, accum_kinds)
    with _LOCK:
        row = conn.execute(
            "SELECT count(*) FROM review_state r "
            "LEFT JOIN wrong_items w ON r.item_type = 'wrong' AND w.id = r.item_id "
            "LEFT JOIN vocab_items v ON r.item_type = 'vocab' AND v.id = r.item_id "
            "LEFT JOIN cet6_accum_items a ON r.item_type = 'accum' AND a.id = r.item_id "
            "WHERE " + where, args).fetchone()
    return int(row[0] or 0)


def review_counts(conn: sqlite3.Connection, *, today=None,
                  item_type: str = "", item_types: tuple = (),
                  sources: tuple = (), accum_kinds: tuple = ()) -> dict:
    """英语复习两个 tab 的计数：到期 / 新卡 / 总数 / 今日已复习 / 下张到期。"""
    day = str(today or dt.date.today().isoformat())[:10]
    types = (item_type,) if item_type in REVIEW_ITEM_TYPES else tuple(item_types)
    valid = [
        "(r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0))",
        "(r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active'))",
        "(r.item_type <> 'accum' OR a.id IS NOT NULL)",
    ]
    conds = list(valid)
    args: list = []
    if types:
        conds.append("r.item_type IN (" + ",".join("?" * len(types)) + ")")
        args.extend(types)
    src = tuple(s for s in sources if s)
    if src:
        conds.append("(r.item_type <> 'wrong' OR w.source IN ("
                     + ",".join("?" * len(src)) + "))")
        args.extend(src)
    kinds = tuple(k for k in accum_kinds if k)
    if kinds:
        conds.append("(r.item_type <> 'accum' OR a.kind IN ("
                     + ",".join("?" * len(kinds)) + "))")
        args.extend(kinds)
    base = ("FROM review_state r "
            "LEFT JOIN wrong_items w ON r.item_type = 'wrong' AND w.id = r.item_id "
            "LEFT JOIN vocab_items v ON r.item_type = 'vocab' AND v.id = r.item_id "
            "LEFT JOIN cet6_accum_items a ON r.item_type = 'accum' AND a.id = r.item_id "
            "WHERE " + " AND ".join(conds))
    with _LOCK:
        total = conn.execute("SELECT count(*) " + base, args).fetchone()[0]
        new = conn.execute(
            "SELECT count(*) " + base + " AND r.state = 'new'", args).fetchone()[0]
        due = conn.execute(
            "SELECT count(*) " + base + " AND r.due <= ?", [*args, day]).fetchone()[0]
        next_row = conn.execute(
            "SELECT min(r.due) " + base + " AND r.due > ?", [*args, day]).fetchone()
        # 今日已复习：复用 base 的有效性/来源/accum_kind 过滤，按「今天动过的不同卡片」数；
        # 不按 review_log 行数，避免同一张卡重复评分被算两次，也不会把另一 tab 的 accum 算进来。
        reviewed = conn.execute(
            "SELECT count(*) " + base
            + " AND substr(r.last_review, 1, 10) = ?",
            [*args, day]).fetchone()[0]
    return {"due": int(due or 0), "new": int(new or 0), "total": int(total or 0),
            "reviewed_today": int(reviewed or 0),
            "next_due": (next_row[0] if next_row else "") or ""}


def review_stats(conn: sqlite3.Connection, today=None, item_type: str = "") -> dict:
    day = str(today or dt.date.today().isoformat())[:10]
    filtered = item_type in REVIEW_ITEM_TYPES
    type_sql = " AND item_type = ?" if filtered else ""
    type_args = [item_type] if filtered else []
    join_filter = " AND r.item_type = ?" if filtered else ""
    join_args = [item_type] if filtered else []
    # 统计与复习队列同口径：已归档生词、已掌握错题不算进总数/新词。
    valid = ("(r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0)) "
             "AND (r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active'))")
    base = ("FROM review_state r "
            "LEFT JOIN wrong_items w ON r.item_type = 'wrong' AND w.id = r.item_id "
            "LEFT JOIN vocab_items v ON r.item_type = 'vocab' AND v.id = r.item_id "
            "WHERE " + valid)
    with _LOCK:
        total = conn.execute(
            "SELECT count(*) " + base + join_filter,
            join_args).fetchone()[0]
        new = conn.execute(
            "SELECT count(*) " + base + " AND r.state = 'new'" + join_filter,
            join_args).fetchone()[0]
        reviewed = conn.execute(
            "SELECT count(*) FROM review_log WHERE substr(ts, 1, 10) = ?" + type_sql,
            [day, *type_args]).fetchone()[0]
        next_row = conn.execute(
            _review_join_sql() + "WHERE r.due > ? "
            "AND (r.item_type <> 'wrong' OR (w.id IS NOT NULL AND w.mastered = 0)) "
            "AND (r.item_type <> 'vocab' OR (v.id IS NOT NULL AND v.status = 'active')) "
            + join_filter + " ORDER BY r.due LIMIT 1",
            [day, *join_args]).fetchone()
    due = len(due_review_items(conn, limit=500, today=day, item_type=item_type))
    return {"due": due, "new": int(new or 0), "total": int(total or 0),
            "reviewed_today": int(reviewed or 0),
            "next_due": (next_row[3] if next_row else "") or ""}


def count_introduced(conn: sqlite3.Connection, *, day: str,
                     item_types: tuple, sources: tuple = ()) -> int:
    """今天新卡进复习的条数（`state_before='new'`），可按来源白名单过滤。"""
    types = tuple(str(t) for t in item_types if t)
    if not types:
        return 0
    placeholders = ",".join("?" * len(types))
    where = ["substr(ts, 1, 10) = ?", "state_before = 'new'",
             f"item_type IN ({placeholders})"]
    args: list = [str(day)[:10], *types]
    src = tuple(s for s in sources if s)
    if src and "wrong" in types:
        marks = ",".join("?" * len(src))
        where.append("(item_type <> 'wrong' OR item_id IN "
                     f"(SELECT id FROM wrong_items WHERE source IN ({marks})))")
        args.extend(src)
    row = conn.execute(
        "SELECT count(*) FROM review_log WHERE " + " AND ".join(where),
        args).fetchone()
    return int(row[0] or 0)


def recent_review_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            "SELECT id, ts, item_type, item_id, rating, state_before, due_before, "
            "due_after, stability, difficulty, elapsed_days, scheduled_days "
            "FROM review_log ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit or 20), 200)),)).fetchall()
    return [{
        "id": row[0], "ts": row[1], "item_type": row[2], "item_id": int(row[3]),
        "rating": int(row[4]), "state_before": row[5] or "",
        "due_before": row[6] or "", "due_after": row[7] or "",
        "stability": float(row[8] or 0), "difficulty": float(row[9] or 0),
        "elapsed_days": int(row[10] or 0), "scheduled_days": int(row[11] or 0),
    } for row in rows]
