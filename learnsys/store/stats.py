"""概览 / 今日页 / 复盘素材的只读聚合。

这里只做 SQL 与行 → dict；学习点、等级、连续天数、行动卡等业务规则在 services。
路由层不再直接写 SQL —— 统计口径要改，先改这里。
"""
from __future__ import annotations

import sqlite3

from ._base import now
from .events import event_kind_counts


# ---------- 概览 ----------

def focus_spans(conn: sqlite3.Connection, day: str = "") -> list[dict]:
    """专注会话的起止时间；未结束的会话用「此刻」兜底，由调用方算分钟。"""
    rows = conn.execute(
        "SELECT started_at, COALESCE(ended_at, '') FROM sessions").fetchall()
    out = []
    for started, ended in rows:
        if day and not str(started).startswith(day):
            continue
        out.append({"started": str(started), "ended": str(ended or now())})
    return out


def activity_counts(conn: sqlite3.Connection, day: str = "") -> dict:
    """问答 / 转写 / 六级断点 / 收藏 / 训练等条数；`day` 为空 = 全量。"""
    like = f"{day}%" if day else "%"

    def one(sql: str) -> int:
        return int(conn.execute(sql, (like,)).fetchone()[0] or 0)

    train = event_kind_counts(conn, "train", day=day)
    return {
        "asks": one("SELECT COUNT(*) FROM asks WHERE ts LIKE ?"),
        "starred": one("SELECT COUNT(*) FROM wrong_items WHERE auto = 0 AND ts LIKE ?"),
        "transcripts": one("SELECT COUNT(*) FROM transcripts WHERE ts_start LIKE ?"),
        "cet6": one("SELECT COUNT(*) FROM cet6_events WHERE ts LIKE ?"),
        "netlab": one("SELECT COUNT(*) FROM events WHERE module = 'netlab' AND ts LIKE ?"),
        "review": one("SELECT COUNT(*) FROM events WHERE module = 'review' "
                      "AND kind = 'report' AND ts LIKE ?"),
        "quiz": one("SELECT COUNT(*) FROM events WHERE module = 'quiz' "
                    "AND kind = 'quiz' AND ts LIKE ?"),
        "train_writing": int(train.get("writing") or 0),
        "train_translation": int(train.get("translation") or 0),
        "train_sentence": int(train.get("sentence") or 0),
    }


def active_days(conn: sqlite3.Connection) -> set[str]:
    """有过学习记录的日期集合（连续天数口径）。"""
    days: set[str] = set()
    queries = (
        "SELECT DISTINCT substr(ts, 1, 10) FROM asks",
        "SELECT DISTINCT substr(ts_start, 1, 10) FROM transcripts",
        "SELECT DISTINCT substr(ts, 1, 10) FROM cet6_events",
        "SELECT DISTINCT substr(ts, 1, 10) FROM events "
        "WHERE module IN ('netlab', 'review', 'quiz', 'materials', 'train')",
        "SELECT DISTINCT substr(started_at, 1, 10) FROM sessions",
        "SELECT DISTINCT substr(last_review, 1, 10) FROM wrong_items "
        "WHERE last_review <> ''",
    )
    for sql in queries:
        try:
            for (day,) in conn.execute(sql).fetchall():
                if day:
                    days.add(str(day)[:10])
        except Exception:
            continue
    return days


def week_asks(conn: sqlite3.Connection, since: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM asks WHERE substr(ts,1,10) >= ?", (since,)
    ).fetchone()[0] or 0)


# ---------- 今日页 ----------

def ask_count(conn: sqlite3.Connection, day: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (f"{day}%",)).fetchone()[0] or 0)


def transcript_totals(conn: sqlite3.Connection, day: str) -> dict:
    count, chars = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts "
        "WHERE ts_start LIKE ?", (f"{day}%",)).fetchone()
    return {"count": int(count or 0), "chars": int(chars or 0)}


def cet6_groups(conn: sqlite3.Connection, day: str, limit: int = 10) -> list[dict]:
    """当天按 卷/题型/小节 聚合的六级断点。"""
    try:
        rows = conn.execute(
            "SELECT paper_title, section, item, COUNT(*), MAX(ts), MAX(paper_id) "
            "FROM cet6_events WHERE ts LIKE ? GROUP BY paper_title, section, item "
            "ORDER BY MAX(ts) DESC LIMIT ?", (f"{day}%", limit)).fetchall()
    except Exception:
        return []
    return [{"paper": row[0] or "", "section": row[1] or "", "item": row[2] or "",
             "count": int(row[3] or 0), "last": row[4] or "",
             "paper_id": row[5] or row[0] or ""} for row in rows]


def latest_cet6_group(conn: sqlite3.Connection, day: str) -> dict | None:
    """某天断点最多的一组（「接着昨天的断点」用）。"""
    row = conn.execute(
        "SELECT paper_title, section, item, COUNT(*), MAX(paper_id) FROM cet6_events "
        "WHERE ts LIKE ? GROUP BY paper_title, section, item "
        "ORDER BY COUNT(*) DESC, MAX(ts) DESC LIMIT 1", (f"{day}%",)).fetchone()
    if not row:
        return None
    return {"paper": row[0], "section": row[1], "item": row[2],
            "count": int(row[3] or 0), "paper_id": row[4]}


def latest_material_event(conn: sqlite3.Connection, day: str) -> dict | None:
    row = conn.execute(
        "SELECT title, COUNT(*) FROM events WHERE module='materials' AND ts LIKE ? "
        "GROUP BY title ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT 1",
        (f"{day}%",)).fetchone()
    if not row:
        return None
    return {"title": row[0], "count": int(row[1] or 0)}


def latest_unmastered_question(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT question FROM wrong_items WHERE mastered=0 "
        "ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    return str(row[0] or "") if row else ""


def sessions_of_day(conn: sqlite3.Connection, day: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions "
        "WHERE started_at LIKE ? ORDER BY id", (f"{day}%",)).fetchall()
    return [{"id": row[0], "started": row[1], "ended": row[2]} for row in rows]


def module_titles(conn: sqlite3.Connection, module: str, day: str,
                  limit: int = 10) -> list[str]:
    rows = conn.execute(
        "SELECT title FROM events WHERE module=? AND ts LIKE ? "
        "ORDER BY id DESC LIMIT ?", (module, f"{day}%", limit)).fetchall()
    return [str(row[0] or "") for row in rows]


def grouped_events(conn: sqlite3.Connection, module: str, day: str,
                   limit: int = 10) -> list[dict]:
    """某模块当天按 (kind, title) 聚合的事件；新→旧。"""
    rows = conn.execute(
        "SELECT kind, title, COUNT(*) FROM events WHERE module=? "
        "AND ts LIKE ? GROUP BY kind, title ORDER BY MAX(id) DESC LIMIT ?",
        (module, f"{day}%", limit)).fetchall()
    return [{"kind": row[0], "title": row[1], "count": int(row[2] or 0)}
            for row in rows]


def module_count(conn: sqlite3.Connection, module: str, day: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM events WHERE module=? AND ts LIKE ?",
        (module, f"{day}%")).fetchone()[0] or 0)


def cet6_count(conn: sqlite3.Connection, day: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM cet6_events WHERE ts LIKE ?",
        (f"{day}%",)).fetchone()[0] or 0)
