"""SSE / 流水摘要 / 历史配对。"""
from __future__ import annotations

import json

from learnsys import store
from learnsys.agent.run_record import clip as _clip
from learnsys.agent.run_record import trace_event as _trace_event


def _sse(kind: str, text: str = "", data: dict | None = None) -> str:
    return "data: " + json.dumps(
        {"kind": kind, "text": text, "data": data or {}}, ensure_ascii=False) + "\n\n"


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
