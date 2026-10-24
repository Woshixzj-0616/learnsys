"""运行流水与成本面板：只读 agent_runs 这一份流水。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from learnsys import store
from learnsys.agent import cost as agent_cost
from learnsys.agent.config import load_config
from learnsys.server.security import require_token

router = APIRouter()


@router.get("/api/agent/runs")
def agent_runs(conversation_id: int = 0, limit: int = 20,
               _=Depends(require_token)):
    conn = store.connect()
    try:
        return {"items": store.list_agent_runs(
            conn, conversation_id=conversation_id, limit=limit)}
    finally:
        conn.close()


@router.get("/api/agent/runs/{run_id}")
def agent_run(run_id: str, _=Depends(require_token)):
    conn = store.connect()
    try:
        row = store.get_agent_run(conn, run_id=run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")
        return row
    finally:
        conn.close()


@router.get("/api/agent/routes/stats")
def agent_route_stats(days: int = 14, _=Depends(require_token)):
    """影子路由汇总：建议档分布、升级率、每日明细；只读 agent_runs。"""
    days = max(0, min(int(days or 14), 365))
    conn = store.connect()
    try:
        return store.route_stats(conn, days=days)
    finally:
        conn.close()


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return int(ordered[index])


@router.get("/api/agent/stats")
def agent_stats(days: int = 7, limit: int = 200, _=Depends(require_token)):
    """运行面板：最近 N 次、按工具聚合、异常列表；只读 agent_runs 这一份流水。"""
    days = max(0, min(int(days or 7), 365))
    limit = max(1, min(int(limit or 200), 500))
    conn = store.connect()
    try:
        runs = store.list_agent_runs(conn, limit=limit)
    finally:
        conn.close()
    if days:
        cutoff = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
        runs = [run for run in runs if str(run.get("started_at") or "")[:10] >= cutoff]

    cfg = load_config()
    price_configured = bool(cfg.price_input or cfg.price_output
                            or cfg.price_cache_read)
    by_tool: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    anomalies: list[dict] = []
    recent: list[dict] = []
    first_values: list[int] = []
    total_values: list[int] = []
    tokens = {"prompt_tokens": 0, "completion_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0,
              "total_tokens": 0}
    cost_sum = 0.0
    error_runs = 0
    currency = ""

    for run in runs:
        counts = agent_cost.normalize_usage(run.get("usage"))
        for key in tokens:
            tokens[key] += int(counts.get(key) or 0)
        run_cost = float(run.get("cost") or 0)
        if not run_cost and price_configured:
            run_cost = agent_cost.estimate(run.get("usage"), cfg)[0]
        run_currency = str(run.get("currency") or "")
        if not currency and run_currency:
            currency = run_currency
        cost_sum += run_cost
        if run.get("first_ms") is not None:
            first_values.append(int(run["first_ms"]))
        if run.get("total_ms"):
            total_values.append(int(run["total_ms"]))
        day = str(run.get("started_at") or "")[:10] or "未知"
        bucket = daily.setdefault(day, {"date": day, "runs": 0, "tokens": 0,
                                        "cost": 0.0, "errors": 0})
        bucket["runs"] += 1
        bucket["tokens"] += int(counts["total_tokens"])
        bucket["cost"] += run_cost
        model = str(run.get("model") or "未记录")
        model_bucket = by_model.setdefault(model, {"model": model, "runs": 0,
                                                   "tokens": 0, "cost": 0.0,
                                                   "total_ms": 0})
        model_bucket["runs"] += 1
        model_bucket["tokens"] += int(counts["total_tokens"])
        model_bucket["cost"] += run_cost
        model_bucket["total_ms"] += int(run.get("total_ms") or 0)

        failed_tools: list[str] = []
        check_issues: list[str] = []
        tool_calls_counted = 0
        for event in run.get("trace") or []:
            kind = event.get("kind")
            data = event.get("data") or {}
            name = str(data.get("name") or "")
            if kind == "tool_start" and name:
                tool_calls_counted += 1
                entry = by_tool.setdefault(
                    name, {"name": name, "calls": 0, "failures": 0,
                           "ms": 0, "ms_calls": 0})
                entry["calls"] += 1
            elif kind == "tool_end" and name and name != "make_plan":
                entry = by_tool.setdefault(
                    name, {"name": name, "calls": 0, "failures": 0,
                           "ms": 0, "ms_calls": 0})
                if data.get("ms") is not None:
                    entry["ms"] += int(data.get("ms") or 0)
                    entry["ms_calls"] += 1
                if data.get("ok") is False:
                    entry["failures"] += 1
                    if name not in failed_tools:
                        failed_tools.append(name)
            elif kind == "check":
                check_issues.extend(str(item) for item in
                                    (data.get("issues") or [])[:5])
        has_error = bool(run.get("error") or int(run.get("error_count") or 0))
        if has_error:
            error_runs += 1
        if has_error or run.get("check_ok") is False:
            issues = []
            if run.get("error"):
                issues.append(str(run["error"])[:200])
            if failed_tools:
                issues.append("工具失败：" + "、".join(failed_tools))
            issues.extend(check_issues[:5])
            anomalies.append({
                "id": run.get("id"), "started_at": run.get("started_at"),
                "conversation_id": run.get("conversation_id"),
                "question": " ".join(str(run.get("question") or "").split())[:80],
                "issues": issues[:6],
            })
        recent.append({
            "id": run.get("id"), "started_at": run.get("started_at"),
            "conversation_id": run.get("conversation_id"),
            "question": " ".join(str(run.get("question") or "").split())[:100],
            "model": run.get("model") or "", "mode": run.get("mode") or "",
            "first_ms": run.get("first_ms"), "total_ms": run.get("total_ms") or 0,
            "steps": run.get("steps") or 0,
            "tool_count": int(run.get("tool_count") or tool_calls_counted),
            "model_calls": run.get("model_calls") or 0,
            "tokens": counts["total_tokens"],
            "prompt_tokens": counts["prompt_tokens"],
            "completion_tokens": counts["completion_tokens"],
            "cache_read_tokens": counts["cache_read_tokens"],
            "cost": round(run_cost, 6), "currency": run_currency or currency,
            "check_ok": run.get("check_ok"), "error": run.get("error") or "",
            "error_count": run.get("error_count") or 0,
        })

    tools = sorted(by_tool.values(), key=lambda item: (-item["calls"],
                                                       item["name"]))
    for item in tools:
        item["avg_ms"] = (int(item["ms"] / item["ms_calls"])
                          if item["ms_calls"] else 0)
    models = sorted(by_model.values(), key=lambda item: -item["runs"])
    for item in models:
        item["avg_total_ms"] = (int(item["total_ms"] / item["runs"])
                                if item["runs"] else 0)
    return {
        "days": days,
        "runs": len(runs),
        "errors": error_runs,
        "totals": {
            "first_ms_avg": int(sum(first_values) / len(first_values))
            if first_values else 0,
            "total_ms_avg": int(sum(total_values) / len(total_values))
            if total_values else 0,
            "total_ms_p95": _percentile(total_values, 0.95),
            **tokens,
            "cost": round(cost_sum, 6),
            "currency": currency,
            "price_configured": price_configured,
        },
        "by_tool": tools,
        "by_model": models,
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
        "anomalies": anomalies[:20],
        "recent": recent,
    }
