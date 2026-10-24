"""Agent 运行流水：一次运行一行，计划 / 工具 / 确认 / 自检都在 trace 里。"""
from __future__ import annotations

import json
import sqlite3

from ._base import _LOCK


# ---- Agent 运行流水（P16.1） ----
#
# 一次运行一行：计划、工具、确认、自检都在 trace 里。
# P16.3 的成本面板直接读这张表，不再另起一份流水。

def add_agent_run(conn: sqlite3.Connection, *, run_id: str,
                  conversation_id: int = 0, question: str = "", model: str = "",
                  mode: str = "", started_at: str = "", finished_at: str = "",
                  first_ms: int | None = None, total_ms: int = 0,
                  steps: int = 0, stop_reason: str = "",
                  usage: dict | None = None, trace: list | None = None,
                  check_ok: bool | None = None, error: str = "",
                  tool_count: int = 0, model_calls: int = 0,
                  error_count: int = 0, cost: float = 0.0,
                  currency: str = "") -> str:
    payload = json.dumps(usage or {}, ensure_ascii=False)
    events = json.dumps(trace or [], ensure_ascii=False)
    with _LOCK:
        conn.execute(
            "INSERT OR REPLACE INTO agent_runs "
            "(run_id, conversation_id, question, model, mode, started_at, finished_at, "
            "first_ms, total_ms, steps, stop_reason, usage_json, trace_json, check_ok, error, "
            "tool_count, model_calls, error_count, cost, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(run_id), int(conversation_id or 0), str(question or ""),
             str(model or ""), str(mode or ""), str(started_at or ""),
             str(finished_at or ""),
             None if first_ms is None else int(first_ms),
             int(total_ms or 0), int(steps or 0), str(stop_reason or ""),
             payload, events,
             None if check_ok is None else (1 if check_ok else 0),
             str(error or ""), int(tool_count or 0), int(model_calls or 0),
             int(error_count or 0), float(cost or 0), str(currency or "")))
        conn.commit()
    return str(run_id)


def _agent_run_dict(row) -> dict:
    def _json(raw, fallback):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return fallback
    return {
        "id": row[1] or "", "conversation_id": int(row[2] or 0),
        "question": row[3] or "", "model": row[4] or "", "mode": row[5] or "",
        "started_at": row[6] or "", "finished_at": row[7] or "",
        "first_ms": row[8], "total_ms": int(row[9] or 0),
        "steps": int(row[10] or 0), "stop_reason": row[11] or "",
        "usage": _json(row[12], {}), "trace": _json(row[13], []),
        "check_ok": None if row[14] is None else bool(row[14]),
        "error": row[15] or "",
        "tool_count": int(row[16] or 0), "model_calls": int(row[17] or 0),
        "error_count": int(row[18] or 0), "cost": float(row[19] or 0),
        "currency": row[20] or "",
    }


_AGENT_RUN_COLUMNS = (
    "id, run_id, conversation_id, question, model, mode, started_at, finished_at, "
    "first_ms, total_ms, steps, stop_reason, usage_json, trace_json, check_ok, error, "
    "tool_count, model_calls, error_count, cost, currency"
)


def get_agent_run(conn: sqlite3.Connection, *, run_id: str = "",
                  row_id: int = 0) -> dict | None:
    with _LOCK:
        if run_id:
            row = conn.execute(
                f"SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE run_id = ?",
                (str(run_id),)).fetchone()
        else:
            row = conn.execute(
                f"SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs WHERE id = ?",
                (int(row_id),)).fetchone()
    return _agent_run_dict(row) if row is not None else None


def list_agent_runs(conn: sqlite3.Connection, conversation_id: int = 0,
                    limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit or 20), 100))
    with _LOCK:
        if conversation_id:
            rows = conn.execute(
                f"SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (int(conversation_id), limit)).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_AGENT_RUN_COLUMNS} FROM agent_runs "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_agent_run_dict(row) for row in rows]


def route_stats(conn: sqlite3.Connection, *, days: int = 14,
                limit: int = 2000) -> dict:
    """影子路由汇总：从 trace_json 里读 route 事件，不新增表。

    `would_escalate` = 建议档为 deep（shadow）或实际档为 deep（on）；
    影子阶段看这个数就知道「开了会多花多少」。
    """
    days = max(0, min(int(days or 0), 365))
    limit = max(1, min(int(limit or 2000), 5000))
    cutoff = ""
    if days:
        import datetime as _dt
        cutoff = (_dt.date.today() - _dt.timedelta(days=days - 1)).isoformat()
    with _LOCK:
        if cutoff:
            rows = conn.execute(
                "SELECT started_at, question, trace_json FROM agent_runs "
                "WHERE substr(started_at, 1, 10) >= ? ORDER BY id DESC LIMIT ?",
                (cutoff, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT started_at, question, trace_json FROM agent_runs "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    total = len(rows)
    with_route = 0
    escalations = 0
    auto_modes: dict[str, int] = {}
    actual_tiers: dict[str, int] = {}
    recommended_tiers: dict[str, int] = {}
    recommended_models: dict[str, int] = {}
    reasons: dict[str, int] = {}
    daily: dict[str, dict] = {}
    samples: list[dict] = []

    def bump(bucket: dict, key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    for started_at, question, trace_raw in rows:
        day = str(started_at or "")[:10]
        if cutoff and day < cutoff:
            continue
        bucket = daily.setdefault(day, {"day": day, "runs": 0,
                                        "routes": 0, "escalations": 0})
        bucket["runs"] += 1
        try:
            trace = json.loads(trace_raw or "[]")
        except (json.JSONDecodeError, TypeError):
            trace = []
        route = next((item for item in trace
                      if isinstance(item, dict) and item.get("kind") == "route"), None)
        if not route:
            continue
        data = route.get("data") or {}
        with_route += 1
        bucket["routes"] += 1
        auto = str(data.get("auto") or "off")
        bump(auto_modes, auto)
        actual = str(data.get("tier") or "")
        if actual:
            bump(actual_tiers, actual)
        rec = data.get("recommended") if isinstance(data.get("recommended"), dict) else {}
        rec_tier = str(rec.get("tier") or actual)
        if rec_tier:
            bump(recommended_tiers, rec_tier)
        rec_model = str(rec.get("model") or data.get("model") or "")
        if rec_model:
            bump(recommended_models, rec_model)
        reason = str((rec or {}).get("reason") or data.get("reason") or "")
        if reason:
            bump(reasons, reason.split("：")[0])
        escalate = rec_tier == "deep" if auto == "shadow" else actual == "deep"
        if escalate:
            escalations += 1
            bucket["escalations"] += 1
            if len(samples) < 5:
                samples.append({"question": str(question or "")[:60],
                                "reason": reason,
                                "model": rec_model or str(data.get("model") or "")})

    ordered_daily = [daily[key] for key in sorted(daily)]
    return {
        "days": days,
        "since": cutoff,
        "runs": total,
        "with_route": with_route,
        "escalations": escalations,
        "escalation_rate": round(escalations / with_route, 3) if with_route else 0.0,
        "auto_modes": auto_modes,
        "actual_tiers": actual_tiers,
        "recommended_tiers": recommended_tiers,
        "recommended_models": recommended_models,
        "reasons": sorted(({"reason": key, "count": value}
                           for key, value in reasons.items()),
                          key=lambda item: -item["count"])[:10],
        "daily": ordered_daily,
        "samples": samples,
    }
