"""智能旅行 `trace_log` 的只读视图（学习工作台「调用路径」页用）。

只读、不建表、不写库：
- 默认读 `D:\\Desktop\\智能旅行\\backend\\travel.db`，可在 `设置.json` 的
  `agent_trace.travel_db` 覆盖，或设环境变量 `LEARNSYS_TRAVEL_DB`；
- 库不在 / 表不在 / 读失败一律回空清单 + 中文原因，不抛到路由层。

这一层只做「读出来 + 轻量摘要」；时间线怎么画在前端 `web/js/pages/agent-trace.js`。
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse

from learnsys import config

DEFAULT_DB = r"D:\Desktop\智能旅行\backend\travel.db"


def db_path() -> str:
    """旅行库路径：设置 > 环境变量 > 默认。"""
    raw = config.USER.get("agent_trace")
    if isinstance(raw, dict):
        text = str(raw.get("travel_db") or "").strip()
        if text:
            return text
    return (os.environ.get("LEARNSYS_TRAVEL_DB", "").strip()
            or DEFAULT_DB)


def _connect():
    """只读连接；库不在 / 打不开 -> None（绝不创建库文件）。"""
    path = db_path()
    if not os.path.exists(path):
        return None
    uri = "file:" + urllib.parse.quote(path.replace("\\", "/"), safe="/:") + "?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True, timeout=3)
    except sqlite3.Error:
        return None


def _flow(text) -> dict:
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _summary(flow: dict) -> dict:
    evs = flow.get("evs") if isinstance(flow.get("evs"), list) else []
    ask = next((e for e in evs if e.get("e") == "ask"), {}) or {}
    end = next((e for e in evs if e.get("e") == "end"), {}) or {}
    spans = next((e for e in evs if e.get("e") == "spans"), {}) or {}
    llm = [e for e in evs if e.get("e") == "llm"]
    tools = [e for e in evs if e.get("e") == "tool"]
    nudge = [e for e in evs if e.get("e") == "nudge"]
    return {
        "question": str(ask.get("q") or "")[:120],
        "ended": str(end.get("ended") or ""),
        "rounds": int(end.get("rounds") or 0),
        "calls": int(end.get("calls") or 0),
        "chars": int(end.get("chars") or 0),
        "llm_calls": len(llm),
        "tool_calls": len(tools),
        "nudges": len(nudge),
        "total_ms": int(spans.get("total_ms") or 0),
        "llm_ms": int(spans.get("llm_ms") or 0),
        "tools_ms": int(spans.get("tools_ms") or 0),
    }


def _empty(why: str) -> dict:
    return {"ok": False, "why": why, "db": db_path(), "items": []}


def list_recent(limit: int = 30, username: str = "") -> dict:
    """最近的 /api/chat 请求（新→旧），带摘要；不返回完整 flow。"""
    limit = max(1, min(int(limit or 30), 100))
    user = str(username or "").strip()
    con = _connect()
    if con is None:
        return _empty("找不到智能旅行库（或打不开）；先确认 backend/travel.db 存在")
    try:
        if user:
            rows = con.execute(
                "select trace_id, at, path, status, ms, username, flow from trace_log "
                "where path='/api/chat' and username=? order by at desc limit ?",
                (user, limit)).fetchall()
        else:
            rows = con.execute(
                "select trace_id, at, path, status, ms, username, flow from trace_log "
                "where path='/api/chat' order by at desc limit ?", (limit,)).fetchall()
    except sqlite3.Error as exc:
        return _empty("读 trace_log 失败：%s" % exc)
    finally:
        con.close()
    items = []
    for trace_id, at, path, status, ms, username, flow_text in rows:
        flow = _flow(flow_text)
        items.append({
            "trace_id": str(trace_id or ""),
            "at": str(at or ""),
            "path": str(path or ""),
            "status": int(status or 0),
            "ms": int(ms or 0),
            "username": str(username or ""),
            "summary": _summary(flow),
        })
    return {"ok": True, "db": db_path(), "items": items}


def get(trace_id: str) -> dict | None:
    """按编号取一条完整流水（含 events）。"""
    key = str(trace_id or "").strip()
    if not key:
        return None
    con = _connect()
    if con is None:
        return None
    try:
        row = con.execute(
            "select trace_id, at, path, status, ms, username, flow from trace_log "
            "where trace_id=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row:
        return None
    trace_id, at, path, status, ms, username, flow_text = row
    flow = _flow(flow_text)
    return {
        "trace_id": str(trace_id or ""),
        "at": str(at or ""),
        "path": str(path or ""),
        "status": int(status or 0),
        "ms": int(ms or 0),
        "username": str(username or ""),
        "summary": _summary(flow),
        "events": flow.get("evs") if isinstance(flow.get("evs"), list) else [],
    }
