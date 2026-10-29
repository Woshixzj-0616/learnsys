"""P26.1 本机 Agent 任务与事件：派活、流式日志、结果留痕。

P26.3 起任务先入队再派发：`add_queued` 落 `queued`，`claim_next` 原子认领，
并发上限与每 agent 串行都在同一条 SQL 的写锁里判定。
"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK, now


STATUSES = ("queued", "running", "done", "failed", "cancelled")
EVENT_KINDS = ("status", "text", "tool", "error", "result")

_TASK_COLUMNS = (
    "id, agent, prompt, workspace, mode, status, exit_code, created_at, "
    "started_at, ended_at, duration_ms, output_path, error, cost_usd, usage_json, "
    "route_json, timeout_s, depends_on, (length(result_text) > 0), project_id, "
    "COALESCE((SELECT p.name FROM project_refs p WHERE p.id = project_id), '')"
)

_UPDATE_FIELDS = {
    "status", "exit_code", "started_at", "ended_at", "duration_ms",
    "output_path", "error", "cost_usd", "usage_json", "route_json",
    "result_text",
}


def _json_dict(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _task_dict(row) -> dict:
    return {
        "id": int(row[0]), "agent": row[1] or "", "prompt": row[2] or "",
        "workspace": row[3] or "", "mode": row[4] or "read",
        "status": row[5] or "queued",
        "exit_code": None if row[6] is None else int(row[6]),
        "created_at": row[7] or "", "started_at": row[8] or "",
        "ended_at": row[9] or "", "duration_ms": int(row[10] or 0),
        "output_path": row[11] or "", "error": row[12] or "",
        "cost_usd": float(row[13] or 0), "usage": _json_dict(row[14]),
        "route": _json_dict(row[15]), "timeout_s": int(row[16] or 0),
        "depends_on": int(row[17] or 0), "has_result": bool(row[18]),
        "project_id": int(row[19] or 0), "project_name": row[20] or "",
        "parent_status": "",
    }


def add_task(conn: sqlite3.Connection, *, agent: str, prompt: str,
             workspace: str = "", mode: str = "read", timeout_s: int = 0,
             route_json: str = "", depends_on: int = 0,
             project_id: int = 0) -> int:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO agent_tasks (agent, prompt, workspace, mode, status, "
            "created_at, route_json, timeout_s, depends_on, project_id) "
            "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
            (str(agent), str(prompt), str(workspace), str(mode), now(),
             str(route_json or ""), max(0, int(timeout_s or 0)),
             max(0, int(depends_on or 0)), max(0, int(project_id or 0))))
        conn.commit()
        return int(cur.lastrowid)


def add_queued(conn: sqlite3.Connection, *, agent: str, prompt: str,
               workspace: str = "", mode: str = "read", timeout_s: int = 0,
               route_json: str = "", queue_max: int = 10,
               depends_on: int = 0, project_id: int = 0) -> int | None:
    """队列未满且父任务可接续才落库；一条 SQL 同时判断与插入。

    返回 None 时调用方要复查父任务，区分「父不可接续」与「队列已满」。
    """
    parent = max(0, int(depends_on or 0))
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO agent_tasks (agent, prompt, workspace, mode, status, "
            "created_at, route_json, timeout_s, depends_on, project_id) "
            "SELECT ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ? "
            "WHERE (SELECT count(*) FROM agent_tasks WHERE status = 'queued') < ? "
            "AND (? = 0 OR EXISTS (SELECT 1 FROM agent_tasks p "
            "     WHERE p.id = ? AND p.status NOT IN ('failed', 'cancelled')))",
            (str(agent), str(prompt), str(workspace), str(mode), now(),
             str(route_json or ""), max(0, int(timeout_s or 0)), parent,
             max(0, int(project_id or 0)),
             max(1, int(queue_max or 10)), parent, parent))
        conn.commit()
        if cur.rowcount <= 0:
            return None
        return int(cur.lastrowid)


def claim_next(conn: sqlite3.Connection, *, max_global: int = 2,
               runner: str = "") -> int | None:
    """原子认领下一个可运行任务：每 agent 串行 + 全局 running 不超上限。

    `runner` 是本进程的实例令牌：恢复时据此区分「自己的任务」与「别人的任务」。
    """
    sql = (
        "UPDATE agent_tasks SET status = 'running', started_at = ?, runner = ?, "
        "heartbeat_at = ? "
        "WHERE id = ("
        "  SELECT t.id FROM agent_tasks t"
        "  WHERE t.status = 'queued'"
        "    AND (t.depends_on = 0 OR EXISTS (SELECT 1 FROM agent_tasks p "
        "         WHERE p.id = t.depends_on AND p.status = 'done'))"
        "    AND NOT EXISTS (SELECT 1 FROM agent_tasks r "
        "                    WHERE r.agent = t.agent AND r.status = 'running')"
        "    AND (SELECT count(*) FROM agent_tasks "
        "         WHERE status = 'running') < ?"
        "  ORDER BY t.id LIMIT 1"
        ") AND status = 'queued' RETURNING id"
    )
    stamp = now()
    with _LOCK:
        row = conn.execute(sql, (stamp, str(runner or ""), stamp,
                                 max(1, int(max_global or 1)))).fetchone()
        conn.commit()
    return int(row[0]) if row else None


def update_task(conn: sqlite3.Connection, task_id: int, **fields) -> None:
    values = {key: value for key, value in fields.items()
              if key in _UPDATE_FIELDS}
    if not values:
        return
    assignments = ", ".join(f"{key} = ?" for key in values)
    with _LOCK:
        conn.execute(f"UPDATE agent_tasks SET {assignments} WHERE id = ?",
                     [*values.values(), int(task_id)])
        conn.commit()


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks WHERE id = ?",
            (int(task_id),)).fetchone()
    if not row:
        return None
    task = _task_dict(row)
    if task["status"] == "queued":
        task["queue_position"] = _queue_position(conn, task)
    else:
        task["queue_position"] = 0
    _attach_parent_status(conn, [task])
    return task


def list_tasks(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit or 20), 200))
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    positions = queue_positions(conn)
    tasks = []
    for row in rows:
        task = _task_dict(row)
        task["queue_position"] = positions.get(task["id"], 0)
        tasks.append(task)
    _attach_parent_status(conn, tasks)
    return tasks


def _attach_parent_status(conn: sqlite3.Connection, tasks: list[dict]) -> None:
    """一次查询补上父任务状态（给界面区分「等待上一步」）。"""
    parents = sorted({task["depends_on"] for task in tasks if task["depends_on"]})
    if not parents:
        return
    marks = ",".join("?" for _ in parents)
    with _LOCK:
        rows = conn.execute(
            f"SELECT id, status FROM agent_tasks WHERE id IN ({marks})",
            parents).fetchall()
    statuses = {int(row[0]): row[1] or "" for row in rows}
    for task in tasks:
        parent = task["depends_on"]
        task["parent_status"] = statuses.get(parent, "") if parent else ""


def queue_positions(conn: sqlite3.Connection) -> dict[int, int]:
    """同 agent 的 queued 按 id 排名；1 = 下一顺位。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT id, ROW_NUMBER() OVER (PARTITION BY agent ORDER BY id) "
            "FROM agent_tasks WHERE status = 'queued'").fetchall()
    return {int(row[0]): int(row[1]) for row in rows}


def _queue_position(conn: sqlite3.Connection, task: dict) -> int:
    position = 0
    with _LOCK:
        row = conn.execute(
            "SELECT count(*) FROM agent_tasks WHERE status = 'queued' "
            "AND agent = ? AND id <= ?",
            (str(task["agent"]), int(task["id"]))).fetchone()
    position = int(row[0] or 0)
    return position


def running_tasks(conn: sqlite3.Connection) -> list[dict]:
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM agent_tasks "
            "WHERE status IN ('queued', 'running') ORDER BY id").fetchall()
    return [_task_dict(row) for row in rows]


def count_running(conn: sqlite3.Connection, agent: str = "") -> int:
    """只统计真正 running 的任务；queued 不占并发名额。"""
    with _LOCK:
        if agent:
            row = conn.execute(
                "SELECT count(*) FROM agent_tasks WHERE status = 'running' "
                "AND agent = ?", (str(agent),)).fetchone()
        else:
            row = conn.execute(
                "SELECT count(*) FROM agent_tasks WHERE status = 'running'"
            ).fetchone()
    return int(row[0] or 0)


def count_queued(conn: sqlite3.Connection) -> int:
    with _LOCK:
        row = conn.execute(
            "SELECT count(*) FROM agent_tasks WHERE status = 'queued'").fetchone()
    return int(row[0] or 0)


def running_count(conn: sqlite3.Connection, agent: str = "") -> int:
    """兼容旧名：现在只算 running（P26.3 起 queued 不进并发上限）。"""
    return count_running(conn, agent=agent)


def cancel_queued(conn: sqlite3.Connection, task_id: int,
                  reason: str = "已取消排队") -> bool:
    with _LOCK:
        cur = conn.execute(
            "UPDATE agent_tasks SET status = 'cancelled', ended_at = ?, error = ? "
            "WHERE id = ? AND status = 'queued'",
            (now(), str(reason or ""), int(task_id)))
        conn.commit()
        return cur.rowcount > 0


def touch_running_tasks(conn: sqlite3.Connection, runner: str) -> int:
    """刷新本进程运行中任务的心跳；没有在跑的任务时不写库。"""
    if not str(runner or ""):
        return 0
    with _LOCK:
        row = conn.execute(
            "SELECT count(*) FROM agent_tasks "
            "WHERE status = 'running' AND runner = ?",
            (str(runner),)).fetchone()
        if int(row[0] or 0) <= 0:
            return 0
        cur = conn.execute(
            "UPDATE agent_tasks SET heartbeat_at = ? "
            "WHERE status = 'running' AND runner = ?",
            (now(), str(runner)))
        conn.commit()
        return int(cur.rowcount or 0)


def fail_stale_running_tasks(conn: sqlite3.Connection, *, runner: str,
                             stale_before: str, error: str) -> list[int]:
    """只回收「不属于本进程、且心跳已过期」的 running。

    `runner = ''` 是升级前遗留的任务，无从确认归属，按过期处理。
    """
    with _LOCK:
        rows = conn.execute(
            "UPDATE agent_tasks SET status = 'failed', ended_at = ?, error = ? "
            "WHERE status = 'running' AND runner != ? "
            "AND (runner = '' OR heartbeat_at = '' OR heartbeat_at < ?) "
            "RETURNING id",
            (now(), str(error or "工作台重启，任务中断"), str(runner or ""),
             str(stale_before or ""))).fetchall()
        conn.commit()
    return [int(row[0]) for row in rows]


def recent_terminal(conn: sqlite3.Connection, agent: str, mode: str,
                    limit: int = 20) -> list[dict]:
    """同一 agent + 模式最近的终态任务，供影子路由算完成率/耗时。"""
    limit = max(1, min(int(limit or 20), 100))
    with _LOCK:
        rows = conn.execute(
            "SELECT status, duration_ms, cost_usd FROM agent_tasks "
            "WHERE agent = ? AND mode = ? "
            "AND status IN ('done', 'failed', 'cancelled') "
            "ORDER BY id DESC LIMIT ?",
            (str(agent), str(mode), limit)).fetchall()
    return [{"status": row[0], "duration_ms": int(row[1] or 0),
             "cost_usd": float(row[2] or 0)} for row in rows]


def get_task_result(conn: sqlite3.Connection, task_id: int) -> str:
    """结果正文只给队列内部做链式注入，不进任务列表。"""
    with _LOCK:
        row = conn.execute(
            "SELECT result_text FROM agent_tasks WHERE id = ?",
            (int(task_id),)).fetchone()
    return str(row[0] or "") if row else ""


def cascade_skipped(conn: sqlite3.Connection) -> list[int]:
    """父任务已失败/已取消/不存在时，把 queued 子任务标成未执行（cancelled）。

    返回被级联的任务 id，调用方负责写事件；调用方循环到返回空列表为止，
    这样孙任务会在下一轮被处理。
    """
    with _LOCK:
        rows = conn.execute(
            "UPDATE agent_tasks SET status = 'cancelled', ended_at = ?, "
            "error = '上一步任务 #' || depends_on || ' 未完成，链已停止' "
            "WHERE status = 'queued' AND depends_on > 0 AND ("
            "  NOT EXISTS (SELECT 1 FROM agent_tasks p WHERE p.id = agent_tasks.depends_on)"
            "  OR EXISTS (SELECT 1 FROM agent_tasks p WHERE p.id = agent_tasks.depends_on"
            "             AND p.status IN ('failed', 'cancelled'))"
            ") RETURNING id", (now(),)).fetchall()
        conn.commit()
    return [int(row[0]) for row in rows]


def add_event(conn: sqlite3.Connection, task_id: int, seq: int,
              kind: str, text: str = "") -> int:
    kind = kind if kind in EVENT_KINDS else "text"
    body = str(text or "")[:4000]
    with _LOCK:
        if int(seq or 0) <= 0:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_task_events "
                "WHERE task_id = ?", (int(task_id),)).fetchone()
            seq = int(row[0] or 1)
        cur = conn.execute(
            "INSERT INTO agent_task_events (task_id, seq, ts, kind, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(task_id), int(seq), now(), kind, body))
        conn.commit()
        return int(cur.lastrowid)


def list_events(conn: sqlite3.Connection, task_id: int,
                after: int = 0, limit: int = 1000) -> list[dict]:
    limit = max(1, min(int(limit or 1000), 5000))
    with _LOCK:
        rows = conn.execute(
            "SELECT seq, ts, kind, text FROM agent_task_events "
            "WHERE task_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (int(task_id), int(after or 0), limit)).fetchall()
    return [{"seq": int(row[0]), "ts": row[1], "kind": row[2],
             "text": row[3] or ""} for row in rows]
