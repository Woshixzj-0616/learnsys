"""检索封存的对话总汇：按关键词找原文片段与锚点。

档案是只读封存物，不参与每轮提示词；Agent 需要旧细节时按需查。
"""
from __future__ import annotations

import pathlib
import re

from .parse import iter_archive_messages

_CACHE: dict[tuple[str, float], list[dict]] = {}


def latest_archive(data_root) -> pathlib.Path | None:
    folder = pathlib.Path(data_root) / "记忆档案"
    try:
        files = sorted(folder.glob("对话总汇-*.md"))
    except OSError:
        return None
    return files[-1] if files else None


def load_messages(path) -> list[dict]:
    path = pathlib.Path(path)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    key = (str(path), stamp)
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = iter_archive_messages(path)
    return _CACHE[key]


def _snippet(text: str, terms: list[str], width: int = 140) -> str:
    lowered = text.casefold()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - width // 2)
    chunk = text[start:start + width * 2]
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if start > 0:
        chunk = "…" + chunk
    if start + width * 2 < len(text):
        chunk += "…"
    return chunk


def search_archive(path, query: str, limit: int = 8) -> list[dict]:
    terms = [term.casefold() for term in str(query or "").split() if term.strip()]
    if not terms:
        return []
    hits: list[dict] = []
    for message in load_messages(path):
        text = message["text"]
        lowered = text.casefold()
        if not all(term in lowered for term in terms):
            continue
        score = sum(lowered.count(term) for term in terms)
        parts = message["anchor"].split("/")
        hits.append({
            "anchor": message["anchor"],
            "source": parts[1] if len(parts) > 1 else "",
            "session_id": parts[2] if len(parts) > 2 else "",
            "at": message.get("at") or "",
            "role": message.get("role") or "",
            "score": score,
            "snippet": _snippet(text, terms),
        })
    hits.sort(key=lambda item: item.get("at") or "", reverse=True)
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:max(1, min(int(limit or 8), 20))]


def read_message(path, anchor: str, max_chars: int = 4000) -> dict | None:
    for message in load_messages(path):
        if message["anchor"] == str(anchor or ""):
            return {**message, "text": message["text"][:max_chars]}
    return None
