"""SSE / 流水摘要 / 历史配对。"""
from __future__ import annotations

import json

from learnsys import store
from learnsys.agent import tools as agent_tools
from .state import _TRACE_KINDS


def _sse(kind: str, text: str = "", data: dict | None = None) -> str:
    return "data: " + json.dumps(
        {"kind": kind, "text": text, "data": data or {}}, ensure_ascii=False) + "\n\n"


def _clip(value, cap: int = 600, depth: int = 0):
    """流水里的参数/结果摘要：截断，不把整份资料或隐私正文写进去。"""
    if depth > 4:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= cap else value[:cap] + "…"
    if isinstance(value, dict):
        return {str(key): _clip(item, cap, depth + 1)
                for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_clip(item, cap, depth + 1) for item in list(value)[:20]]
    return value


def _trace_event(event) -> dict | None:
    if event.kind not in _TRACE_KINDS:
        return None
    data = _clip(event.data or {})
    # 写入/运行类工具的参数可能含正文或代码：流水里只留一句摘要，不存全文。
    if event.kind == "tool_start" and isinstance(event.data, dict):
        name = str(event.data.get("name") or "")
        if name in agent_tools.CONFIRM_TOOLS:
            data["input"] = {"摘要": agent_tools.write_summary(
                name, event.data.get("input") or {})}
    # 代码运行的输出是审计证据，单独放宽到 8KB（其余参数仍按 600 字截断）。
    if isinstance(event.data, dict) and event.data.get("output"):
        data["output"] = str(event.data["output"])[:8000]
    return {"kind": event.kind, "text": _clip(event.text or "", 400),
            "data": data}


def _load_history(conn, conversation_id: int, turns: int = 4) -> list[tuple[str, str]]:
    """把落库的消息配成「问/答」对，喂给 Agent 做多轮上下文。

    只收有正文的问答；出错/中断的消息跳过。兼容 v1 的纯字符串 content。
    """
    pairs: list[tuple[str, str]] = []
    question = ""
    for message in store.conversation_messages(conn, conversation_id):
        content = message.get("content")
        if message.get("role") == "user":
            if isinstance(content, dict):
                question = str(content.get("text") or "")
            elif isinstance(content, str):
                question = content
        elif message.get("role") == "assistant" and question:
            broken = False
            if isinstance(content, dict):
                answer = str(content.get("text") or "")
                # 中断 / 出错留下的半截回答不能当完整答案喂给下一轮。
                broken = bool(content.get("error") or content.get("interrupted"))
            elif isinstance(content, str):
                answer = content
            else:
                answer = ""
            if answer.strip() and not broken:
                pairs.append((question, answer))
            question = ""
    return pairs[-max(1, turns):]
