"""各来源共用的解析工具：JSONL 容错、文本块、注入内容识别、时间。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib


def iter_jsonl(path: pathlib.Path, errors: list[int]):
    """逐行读 JSONL；坏行只计数，不中断整份文件。"""
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        errors[0] += 1
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                errors[0] += 1


def block_text(block) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    kind = block.get("type")
    if kind in ("reasoning", "thinking", "tool_use", "tool_result",
                "function_call", "function_call_output", "image", "file"):
        return ""
    text = block.get("text")
    return text if isinstance(text, str) else ""


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block_text(block) for block in content]
        return "\n".join(part for part in parts if part.strip())
    if isinstance(content, dict):
        return content_text(content.get("content"))
    return ""


_INJECTED_PREFIXES = (
    "<environment_context>",
    "<user_instructions>",
    "<system-reminder>",
    "<local-command",
    "<command-name>",
    "# AGENTS.md",
    "Caveat: The messages below",
    "Current runtime context",
)


def is_injected(text: str) -> bool:
    head = str(text or "").lstrip()
    return any(head.startswith(prefix) for prefix in _INJECTED_PREFIXES)


def clean_text(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    return text.strip()


def file_time(path: pathlib.Path) -> str:
    try:
        return dt.datetime.fromtimestamp(
            path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    except OSError:
        return ""


def before_cutoff(path: pathlib.Path, cutoff_ts: float) -> bool:
    try:
        return path.stat().st_mtime <= cutoff_ts
    except OSError:
        return False


def glob_files(root: pathlib.Path, pattern: str) -> list[pathlib.Path]:
    try:
        return sorted(path for path in root.glob(pattern) if path.is_file())
    except OSError:
        return []
