"""DeepSeek 官方导出：conversations.json 是唯一真源。

Obsidian 里的 `01-对话/*.md` 是这份 JSON 的生成物，不重复导入。
"""
from __future__ import annotations

import json
import pathlib

from ..model import Message, Session, Source
from .common import clean_text, content_text

PATH = pathlib.Path(
    r"D:/cahier/智库/智库/DeepSeek对话归档/02-原始数据/conversations.json")


def _walk(mapping: dict):
    """按 children 顺序遍历消息树；遇到环或坏数据时退回按键排序。"""
    seen: set[str] = set()

    def visit(node_id: str):
        if node_id in seen or node_id not in mapping:
            return
        seen.add(node_id)
        node = mapping.get(node_id) or {}
        yield node
        for child in node.get("children") or []:
            yield from visit(str(child))

    if "root" in mapping:
        yield from visit("root")
        return
    for key in sorted(mapping):
        yield from visit(str(key))


def collect(cutoff_ts: float) -> dict:
    if not PATH.exists():
        return {"files": 0, "sessions": [], "skipped": 0, "errors": 1}
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"files": 1, "sessions": [], "skipped": 0, "errors": 1}
    sessions: list[Session] = []
    skipped = 0
    for conv in raw if isinstance(raw, list) else []:
        messages: list[Message] = []
        mapping = conv.get("mapping") if isinstance(conv, dict) else None
        if not isinstance(mapping, dict):
            continue
        for node in _walk(mapping):
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            for fragment in message.get("fragments") or []:
                if not isinstance(fragment, dict):
                    continue
                kind = fragment.get("type")
                if kind == "REQUEST":
                    role = "user"
                elif kind == "RESPONSE":
                    role = "assistant"
                else:
                    skipped += 1
                    continue
                text = clean_text(content_text(
                    fragment.get("content") or fragment.get("text") or ""))
                if not text:
                    skipped += 1
                    continue
                messages.append(Message(role, text, ""))
        if messages:
            sessions.append(Session(
                source="deepseek", session_id=str(conv.get("id") or ""),
                title=str(conv.get("title") or messages[0].text[:60]),
                at=str(conv.get("inserted_at") or conv.get("updated_at") or ""),
                path=str(PATH), messages=messages))
    return {"files": 1, "sessions": sessions,
            "skipped": skipped, "errors": 0}


SOURCE = Source("deepseek", "DeepSeek", "C", collect)
