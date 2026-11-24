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
    """把落库的消息配成「问/答」对；配对逻辑只在 `store.conversation_pairs`。"""
    return store.conversation_pairs(conn, conversation_id, turns=max(1, turns))
