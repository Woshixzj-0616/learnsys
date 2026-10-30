"""个人域：偏好事实 / 项目引用 / 订阅 / 每日卡片。

只放 SQL 与行转换；业务判定（三格、复习、调度）留在 services。
写操作统一走 `_LOCK`；对外返回 dict，不返回 sqlite3.Row。
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from ._base import _LOCK, now

FACT_KINDS = ("preference", "goal", "constraint")
FACT_STATUSES = ("active", "archived")
PROJECT_STATUSES = ("active", "paused", "archived")
SUBSCRIPTION_KINDS = ("news", "word", "price", "stock", "custom")
CADENCES = ("daily", "weekly")
CARD_DOMAINS = ("learn", "work", "life")

_FACT_COLUMNS = ("id, kind, content, evidence, confidence, status, "
                 "created_at, updated_at")
_PROJECT_COLUMNS = ("id, name, repo_path, handoff_path, status, next_step, "
                    "risk, updated_at")
_SUBSCRIPTION_COLUMNS = ("id, topic, kind, cadence, at_time, sources_json, "
                         "last_run, enabled, created_at, updated_at")
_CARD_COLUMNS = ("id, day, domain, title, content_json, read_at, created_at")


def _json(raw, fallback):
    try:
        value = json.loads(raw or "")
    except Exception:
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _fact_dict(row) -> dict:
    return {
        "id": int(row[0]), "kind": row[1] or "preference",
        "content": row[2] or "", "evidence": row[3] or "",
        "confidence": float(row[4] or 0), "status": row[5] or "active",
        "created_at": row[6] or "", "updated_at": row[7] or "",
    }


def _project_dict(row) -> dict:
    return {
        "id": int(row[0]), "name": row[1] or "",
        "repo_path": row[2] or "", "handoff_path": row[3] or "",
        "status": row[4] or "active", "next_step": row[5] or "",
        "risk": row[6] or "", "updated_at": row[7] or "",
    }


def _subscription_dict(row) -> dict:
    return {
        "id": int(row[0]), "topic": row[1] or "",
        "kind": row[2] or "news", "cadence": row[3] or "daily",
        "at_time": row[4] or "07:30",
        "sources": _json(row[5], []),
        "last_run": row[6] or "", "enabled": bool(row[7]),
        "created_at": row[8] or "", "updated_at": row[9] or "",
    }


def _card_dict(row) -> dict:
    read_at = row[5] or ""
    return {
        "id": int(row[0]), "day": row[1] or "", "domain": row[2] or "life",
        "title": row[3] or "", "content": _json(row[4], {}),
        "read_at": read_at, "read": bool(read_at),
        "created_at": row[6] or "",
    }


# ---------------------------------------------------------------- profile_facts

def list_facts(conn: sqlite3.Connection, *, kind: str = "",
               status: str = "active", limit: int = 200) -> list[dict]:
    sql = f"SELECT {_FACT_COLUMNS} FROM profile_facts WHERE 1 = 1"
    args: list = []
    if kind:
        sql += " AND kind = ?"
        args.append(str(kind))
    if status:
        sql += " AND status = ?"
        args.append(str(status))
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 200), 1000)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_fact_dict(row) for row in rows]


def get_fact(conn: sqlite3.Connection, fact_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM profile_facts WHERE id = ?",
            (int(fact_id),)).fetchone()
    return _fact_dict(row) if row else None


def upsert_fact(conn: sqlite3.Connection, *, content: str,
                fact_id: int = 0, kind: str = "preference",
                evidence: str = "", confidence: float = 0.5,
                status: str = "active") -> dict | None:
    """按 id 更新；`fact_id=0` 时新增一条。"""
    content = str(content or "").strip()
    if not content:
        raise ValueError("偏好内容不能为空")
    stamp = now()
    values = (str(kind or "preference"), content, str(evidence or ""),
              float(confidence), str(status or "active"), stamp)
    with _LOCK:
        if fact_id:
            cur = conn.execute(
                "UPDATE profile_facts SET kind = ?, content = ?, evidence = ?, "
                "confidence = ?, status = ?, updated_at = ? WHERE id = ?",
                (*values, int(fact_id)))
            conn.commit()
            new_id = int(fact_id) if cur.rowcount else 0
        else:
            cur = conn.execute(
                "INSERT INTO profile_facts "
                "(kind, content, evidence, confidence, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (*values, stamp))
            conn.commit()
            new_id = int(cur.lastrowid or 0)
    return get_fact(conn, new_id) if new_id else None


def archive_fact(conn: sqlite3.Connection, fact_id: int) -> dict | None:
    with _LOCK:
        cur = conn.execute(
            "UPDATE profile_facts SET status = 'archived', updated_at = ? "
            "WHERE id = ?", (now(), int(fact_id)))
        conn.commit()
    return get_fact(conn, fact_id) if cur.rowcount else None


# ----------------------------------------------------------------- project_refs

def list_projects(conn: sqlite3.Connection, *, status: str = "",
                  limit: int = 100) -> list[dict]:
    sql = f"SELECT {_PROJECT_COLUMNS} FROM project_refs"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(str(status))
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 500)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_project_dict(row) for row in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM project_refs WHERE id = ?",
            (int(project_id),)).fetchone()
    return _project_dict(row) if row else None


def upsert_project(conn: sqlite3.Connection, *, name: str,
                   repo_path: str = "", handoff_path: str = "",
                   status: str = "active", next_step: str = "",
                   risk: str = "") -> dict:
    """按 `name` 唯一键新增/更新；只存路径与状态，不复制仓库内容。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("项目名不能为空")
    stamp = now()
    with _LOCK:
        conn.execute(
            "INSERT INTO project_refs "
            "(name, repo_path, handoff_path, status, next_step, risk, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET repo_path = excluded.repo_path, "
            "handoff_path = excluded.handoff_path, status = excluded.status, "
            "next_step = excluded.next_step, risk = excluded.risk, "
            "updated_at = excluded.updated_at",
            (name, str(repo_path or ""), str(handoff_path or ""),
             str(status or "active"), str(next_step or ""),
             str(risk or ""), stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM project_refs WHERE name = ?",
            (name,)).fetchone()
    return _project_dict(row)


def set_next_step(conn: sqlite3.Connection, project_id: int,
                  next_step: str) -> dict | None:
    with _LOCK:
        cur = conn.execute(
            "UPDATE project_refs SET next_step = ?, updated_at = ? WHERE id = ?",
            (str(next_step or ""), now(), int(project_id)))
        conn.commit()
    return get_project(conn, project_id) if cur.rowcount else None


_PROJECT_EDITABLE = ("name", "repo_path", "handoff_path", "status",
                     "next_step", "risk")


def update_project(conn: sqlite3.Connection, project_id: int,
                   **changes) -> dict | None:
    """部分更新项目；只认白名单字段，`None` 表示不改。

    重名由表上的 UNIQUE 约束拦截，调用方把 `sqlite3.IntegrityError` 转成 400。
    """
    fields = [(key, str(changes[key])) for key in _PROJECT_EDITABLE
              if key in changes and changes[key] is not None]
    if "name" in [key for key, _ in fields] and not str(changes["name"]).strip():
        raise ValueError("项目名不能为空")
    if not fields:
        return get_project(conn, project_id)
    sets = ", ".join(f"{key} = ?" for key, _ in fields) + ", updated_at = ?"
    args = [value for _, value in fields] + [now(), int(project_id)]
    with _LOCK:
        cur = conn.execute(f"UPDATE project_refs SET {sets} WHERE id = ?", args)
        conn.commit()
    return get_project(conn, project_id) if cur.rowcount else None


def archive_project(conn: sqlite3.Connection, project_id: int) -> dict | None:
    """归档不物理删除：保留路径与交接记录，默认列表不再显示。"""
    return update_project(conn, project_id, status="archived")


# ----------------------------------------------------------------- subscriptions

def list_subscriptions(conn: sqlite3.Connection, *,
                       enabled_only: bool = False) -> list[dict]:
    sql = f"SELECT {_SUBSCRIPTION_COLUMNS} FROM subscriptions"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY id ASC"
    with _LOCK:
        rows = conn.execute(sql).fetchall()
    return [_subscription_dict(row) for row in rows]


def get_subscription(conn: sqlite3.Connection,
                     sub_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_SUBSCRIPTION_COLUMNS} FROM subscriptions WHERE id = ?",
            (int(sub_id),)).fetchone()
    return _subscription_dict(row) if row else None


def upsert_subscription(conn: sqlite3.Connection, *, topic: str,
                        kind: str = "news", cadence: str = "daily",
                        at_time: str = "07:30",
                        sources: list | None = None,
                        enabled: bool = True) -> dict:
    """按 `(topic, kind)` 唯一键新增/更新；更新不重置 `last_run`。"""
    topic = str(topic or "").strip()
    if not topic:
        raise ValueError("订阅主题不能为空")
    stamp = now()
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    with _LOCK:
        conn.execute(
            "INSERT INTO subscriptions "
            "(topic, kind, cadence, at_time, sources_json, enabled, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(topic, kind) DO UPDATE SET "
            "cadence = excluded.cadence, at_time = excluded.at_time, "
            "sources_json = excluded.sources_json, enabled = excluded.enabled, "
            "updated_at = excluded.updated_at",
            (topic, str(kind or "news"), str(cadence or "daily"),
             str(at_time or "07:30"), sources_json, 1 if enabled else 0,
             stamp, stamp))
        conn.commit()
        row = conn.execute(
            f"SELECT {_SUBSCRIPTION_COLUMNS} FROM subscriptions "
            "WHERE topic = ? AND kind = ?",
            (topic, str(kind or "news"))).fetchone()
    return _subscription_dict(row)


_SUBSCRIPTION_EDITABLE = ("topic", "kind", "cadence", "at_time", "enabled")


def update_subscription(conn: sqlite3.Connection, sub_id: int,
                        *, sources: list | None = None,
                        **changes) -> dict | None:
    """部分更新订阅；`sources=None` 表示不改。

    改 `topic` 可能撞 `(topic, kind)` 唯一键，由调用方把 IntegrityError 转 400。
    """
    if changes.get("enabled") is not None:
        changes = dict(changes)
        changes["enabled"] = 1 if changes["enabled"] else 0
    fields = [(key, changes[key]) for key in _SUBSCRIPTION_EDITABLE
              if key in changes and changes[key] is not None]
    if any(key == "topic" and not str(value).strip() for key, value in fields):
        raise ValueError("订阅主题不能为空")
    if sources is not None:
        fields.append(("sources_json",
                       json.dumps(list(sources or []), ensure_ascii=False)))
    if not fields:
        return get_subscription(conn, sub_id)
    sets = ", ".join(f"{key} = ?" for key, _ in fields) + ", updated_at = ?"
    args = [value for _, value in fields] + [now(), int(sub_id)]
    with _LOCK:
        cur = conn.execute(f"UPDATE subscriptions SET {sets} WHERE id = ?", args)
        conn.commit()
    return get_subscription(conn, sub_id) if cur.rowcount else None


def _time_reached(at_time: str, moment: dt.datetime) -> bool:
    """`at_time` 是 HH:MM；解析不了就当作不限制时间。"""
    try:
        hour, minute = (int(part) for part in str(at_time).split(":", 1))
    except (TypeError, ValueError):
        return True
    return (hour, minute) <= (moment.hour, moment.minute)


def _is_due(item: dict, moment: dt.datetime) -> bool:
    if not item["enabled"]:
        return False
    if not _time_reached(item["at_time"], moment):
        return False
    last = str(item["last_run"] or "")[:10]
    if not last:
        return True
    try:
        last_day = dt.date.fromisoformat(last)
    except ValueError:
        return True
    if item["cadence"] == "weekly":
        return (moment.date() - last_day).days >= 7
    return last_day < moment.date()


def due_subscriptions(conn: sqlite3.Connection,
                      at: dt.datetime | None = None) -> list[dict]:
    """此刻该跑的订阅：启用的 + 到了点 + 按频率还没跑过。"""
    moment = at or dt.datetime.now()
    return [item for item in list_subscriptions(conn, enabled_only=True)
            if _is_due(item, moment)]


def mark_run(conn: sqlite3.Connection, sub_id: int, *, ts: str = "") -> dict | None:
    stamp = str(ts or "") or now()
    with _LOCK:
        cur = conn.execute(
            "UPDATE subscriptions SET last_run = ?, updated_at = ? WHERE id = ?",
            (stamp, now(), int(sub_id)))
        conn.commit()
    return get_subscription(conn, sub_id) if cur.rowcount else None


def delete_subscription(conn: sqlite3.Connection,
                        sub_id: int) -> dict | None:
    """硬删一条订阅；已生成的 `daily_cards` 保留（历史卡片不跟着消失）。"""
    item = get_subscription(conn, sub_id)
    if item is None:
        return None
    with _LOCK:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (int(sub_id),))
        conn.commit()
    return item


# ------------------------------------------------------------------- daily_cards

def list_cards(conn: sqlite3.Connection, *, day: str = "", domain: str = "",
               limit: int = 100) -> list[dict]:
    sql = f"SELECT {_CARD_COLUMNS} FROM daily_cards WHERE 1 = 1"
    args: list = []
    if day:
        sql += " AND day = ?"
        args.append(str(day)[:10])
    if domain:
        sql += " AND domain = ?"
        args.append(str(domain))
    sql += " ORDER BY day DESC, id ASC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 1000)))
    with _LOCK:
        rows = conn.execute(sql, args).fetchall()
    return [_card_dict(row) for row in rows]


def list_recent_cards(conn: sqlite3.Connection, *, days: int = 1,
                      limit: int = 30) -> list[dict]:
    """最近 N 天（含今天）的卡片；日期是 ISO 文本，可直接按字符串比较。"""
    days = max(1, min(int(days or 1), 30))
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    limit = max(1, min(int(limit or 30), 500))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_CARD_COLUMNS} FROM daily_cards WHERE day >= ? "
            "ORDER BY day DESC, id ASC LIMIT ?", (since, limit)).fetchall()
    return [_card_dict(row) for row in rows]


def get_card(conn: sqlite3.Connection, card_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_CARD_COLUMNS} FROM daily_cards WHERE id = ?",
            (int(card_id),)).fetchone()
    return _card_dict(row) if row else None


def upsert_card(conn: sqlite3.Connection, *, day: str,
                domain: str = "life", title: str = "",
                content: dict | None = None) -> dict:
    """按 `(day, domain, title)` 唯一键新增/更新；更新不清 `read_at`。"""
    day = str(day or "")[:10]
    if not day:
        raise ValueError("卡片日期不能为空")
    domain = str(domain or "life")
    title = str(title or "")
    with _LOCK:
        conn.execute(
            "INSERT INTO daily_cards (day, domain, title, content_json, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day, domain, title) DO UPDATE SET "
            "content_json = excluded.content_json",
            (day, domain, title,
             json.dumps(content or {}, ensure_ascii=False), now()))
        conn.commit()
        row = conn.execute(
            f"SELECT {_CARD_COLUMNS} FROM daily_cards "
            "WHERE day = ? AND domain = ? AND title = ?",
            (day, domain, title)).fetchone()
    return _card_dict(row)


def mark_read(conn: sqlite3.Connection, card_id: int,
              read: bool = True) -> dict | None:
    with _LOCK:
        cur = conn.execute(
            "UPDATE daily_cards SET read_at = ? WHERE id = ?",
            (now() if read else "", int(card_id)))
        conn.commit()
    return get_card(conn, card_id) if cur.rowcount else None
