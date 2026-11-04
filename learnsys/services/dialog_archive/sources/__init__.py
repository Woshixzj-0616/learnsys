"""对话来源注册表：顺序即档案正文的分节顺序。"""
from __future__ import annotations

from . import claude_code, codebuddy, codex, deepseek, doubao, dsh, qwen, zcode

SOURCES = [
    codex.SOURCE,
    claude_code.SOURCE,
    deepseek.SOURCE,
    qwen.SOURCE,
    codebuddy.SOURCE,
    zcode.SOURCE,
    dsh.SOURCE,
    doubao.SOURCE,
]

__all__ = ["SOURCES"]
