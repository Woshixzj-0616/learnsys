"""工具调用上下文与小工具函数。"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field


@dataclass
class ToolContext:
    data_root: pathlib.Path
    attachment_name: str = ""
    attachment_text: str = ""
    db_path: pathlib.Path | None = None
    conversation_id: int | None = None
    conversation_key: str = ""
    mode: str = ""
    material_id: int = 0          # 从资料出题时带上，错题按资料归档
    code_debug: bool = False      # 代码调试轮：run_code 用更短的超时，减少坏输入的等待
    saved: set[str] = field(default_factory=set)


def _one_line(text: str, cap: int = 300) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= cap else value[:cap] + "…"


def _stamp(value) -> str:
    text = str(value or "")
    return text[:16] if len(text) >= 16 else text


def _safe_path(raw: str, data_root: pathlib.Path) -> pathlib.Path | None:
    """只允许数据根目录里的文件 —— 防止工具被诱导去读系统目录。"""
    try:
        path = pathlib.Path(raw).expanduser().resolve()
        root = data_root.resolve()
        path.relative_to(root)
        return path
    except (OSError, ValueError):
        return None
