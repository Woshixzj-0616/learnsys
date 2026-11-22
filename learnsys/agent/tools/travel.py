"""智能旅行 trace 的只读工具：让学习 agent 能查「最近哪条请求慢 / 怎么走的」。

数据源是 `learnsys.store.agent_trace`（只读旅行 `travel.db` 的 trace_log）；
不登录、不调用旅行 /api/chat、不写任何东西。
"""
from __future__ import annotations

from learnsys.store import agent_trace


def _summary_line(index: int, item: dict) -> str:
    summary = item.get("summary") or {}
    line = (f"{index}. {item.get('trace_id') or '?'} · {item.get('at') or ''} · "
            f"{summary.get('total_ms') or 0} ms"
            f"（模型 {summary.get('llm_ms') or 0} / 工具 {summary.get('tools_ms') or 0}）"
            f" · {summary.get('rounds') or 0} 轮"
            f" · {summary.get('tool_calls') or 0} 个工具"
            f" · {summary.get('nudges') or 0} 次打回")
    question = str(summary.get("question") or "").strip()
    if question:
        line += f"\n   问题：{question[:80]}"
    return line


def _event_line(event: dict) -> str:
    kind = str(event.get("e") or "")
    if kind == "ask":
        return f"ask：{str(event.get('q') or '')[:60]}"
    if kind == "llm":
        return (f"llm：{event.get('ms') or 0} ms · "
                f"输入 {event.get('tin') or 0} / 输出 {event.get('tout') or 0} token")
    if kind == "tool":
        return (f"tool：{event.get('name') or '?'} · "
                f"{'成功' if event.get('ok') else '失败'} · {event.get('ms') or 0} ms")
    if kind == "nudge":
        return f"nudge：{event.get('flag') or event.get('ask') or '打回一次'}"
    if kind == "spans":
        return (f"spans：总 {event.get('total_ms') or 0} ms · "
                f"模型 {event.get('llm_ms') or 0} ms · 工具 {event.get('tools_ms') or 0} ms")
    if kind == "end":
        return (f"end：{event.get('ended') or ''} · {event.get('rounds') or 0} 轮 · "
                f"{event.get('calls') or 0} 次调用")
    return kind or "事件"


def travel_trace_summary(limit: int = 10, trace_id: str = "",
                         slow_only: bool = False) -> str:
    """返回给模型看的中文摘要；缺库/找不到都回中文原因，不抛异常。"""
    key = str(trace_id or "").strip()
    if key:
        data = agent_trace.get(key)
        if not data:
            return f"没有找到智能旅行 trace：{key}（库可能在，但没有这条记录）"
        summary = data.get("summary") or {}
        lines = [
            f"智能旅行 trace {data.get('trace_id')}（{data.get('at') or ''}）",
            (f"总耗时 {summary.get('total_ms') or 0} ms · "
             f"{summary.get('rounds') or 0} 轮 · "
             f"{summary.get('calls') or 0} 次调用"),
            f"问题：{str(summary.get('question') or '')[:120]}",
            "事件（最多 30 条）：",
        ]
        for event in (data.get("events") or [])[:30]:
            if isinstance(event, dict):
                lines.append("· " + _event_line(event))
        return "\n".join(lines)

    data = agent_trace.list_recent(limit=max(1, min(int(limit or 10), 30)))
    if not data.get("ok"):
        return "读智能旅行 trace 失败：" + str(data.get("why") or "库不可用")
    items = list(data.get("items") or [])
    if slow_only:
        items.sort(key=lambda item: int((item.get("summary") or {}).get("total_ms") or 0),
                   reverse=True)
    if not items:
        return "智能旅行还没有 /api/chat 调用记录。"
    lines = [f"智能旅行最近 {len(items)} 条调用路径（只读）："]
    for index, item in enumerate(items, 1):
        lines.append(_summary_line(index, item))
    return "\n".join(lines)
