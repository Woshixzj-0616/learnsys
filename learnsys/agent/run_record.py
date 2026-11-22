"""运行流水的小工具：事件折叠与截断。

唯一落点：服务端对话（`server/routes_agent/chat.py`）和原生快捷栏
（`ask/quickbar/workers.py`）都从这里取 `trace_event`，避免两份流水口径漂移。

这一层只做「把一个 AgentEvent 变成可入库的一行」；不碰数据库、不读配置。
"""
from __future__ import annotations

# 进流水的只读/过程事件；done 上的记忆审计由 trace_event 单独折叠成 memory。
TRACE_KINDS = {
    "plan", "plan_update", "tool_start", "tool_end", "confirm",
    "check", "rewrite", "activity", "error", "route", "gate", "memory",
}


def clip(value, cap: int = 600, depth: int = 0):
    """流水里的参数/结果摘要：截断，不把整份资料或隐私正文写进去。"""
    if depth > 4:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= cap else value[:cap] + "…"
    if isinstance(value, dict):
        return {str(key): clip(item, cap, depth + 1)
                for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [clip(item, cap, depth + 1) for item in list(value)[:20]]
    return value


def trace_event(event) -> dict | None:
    """把一次 AgentEvent 折成流水项；不值得记的返回 None。"""
    # 记忆审计挂在 done 上，不新增事件，避免打乱既有事件顺序断言。
    if event.kind == "done":
        data = event.data if isinstance(event.data, dict) else {}
        memory = data.get("memory")
        prompt = data.get("prompt")
        if memory or prompt:
            payload = {}
            if memory:
                payload.update(clip(memory))
            if prompt:
                payload["prompt"] = clip(prompt)
            if data.get("tool_tokens"):
                payload["tool_tokens"] = int(data["tool_tokens"])
            return {"kind": "memory", "text": "", "data": clip(payload)}
        return None
    if event.kind not in TRACE_KINDS:
        return None
    # 局部导入：agent.tools 会拉起各域工具；放在函数里避免与工具层形成导入环。
    from learnsys.agent import tools as agent_tools

    data = clip(event.data or {})
    # 写入/运行类工具的参数可能含正文或代码：流水里只留一句摘要，不存全文。
    if event.kind == "tool_start" and isinstance(event.data, dict):
        name = str(event.data.get("name") or "")
        if name in agent_tools.CONFIRM_TOOLS:
            data["input"] = {"摘要": agent_tools.write_summary(
                name, event.data.get("input") or {})}
    # 代码运行的输出是审计证据，单独放宽到 8KB（其余参数仍按 600 字截断）。
    if isinstance(event.data, dict) and event.data.get("output"):
        data["output"] = str(event.data["output"])[:8000]
    return {"kind": event.kind, "text": clip(event.text or "", 400),
            "data": data}
