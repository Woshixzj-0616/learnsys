"""对话总汇：一次性把多个 AI 的对话整理成一个封存 Markdown。

真源分工：
- 本包只读外部原始文件，生成 `对话总汇-YYYY-MM-DD.md`；
- 档案是只读封存物，不进每轮提示词；
- 记忆抽取由 `extract.py` 从档案里抽，写入 agent_memories。
"""
from __future__ import annotations

from .build import build_archive, verify_archive
from .model import Message, Session, Source

__all__ = ["Message", "Session", "Source", "build_archive", "verify_archive"]
