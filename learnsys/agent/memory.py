"""Agent 的长期记忆：读给系统提示词，工具负责写。

记忆只有一份 —— `learning.db` 的 `agent_memories` 表：
- Agent 用 `save_memory` / `forget_memory` 改它；
- 每轮对话开始时 `load_for_prompt()` 读出来，拼进系统提示词；
- 设置页也能看、改、删（同一张表，不另存一份文本）。

约束：**一条 = 一条独立、可长期生效的规矩/偏好**。临时任务细节不进来。
"""
from __future__ import annotations

import pathlib

from learnsys import store


def db_path(data_root) -> pathlib.Path:
    return pathlib.Path(data_root or "") / "learning.db"


def load_for_prompt(data_root, *, limit: int = 40, max_chars: int = 4000) -> str:
    """把启用中的记忆拼成一段给模型看的文本；没有就返回空串。"""
    try:
        conn = store.connect(db_path(data_root))
    except Exception:
        return ""
    try:
        items = store.list_memories(conn, limit=limit)
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    lines: list[str] = []
    total = 0
    for item in items:
        line = f"- [#{item['id']}] {item['content']}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def render_for_prompt(data_root) -> str:
    text = load_for_prompt(data_root)
    if not text:
        return (
            "【用户长期记忆】\n"
            "（目前还没有记录。用户一旦提出跨会话的偏好或规矩，先调用 save_memory 记下来，再回答。）"
        )
    return (
        "【用户长期记忆（跨会话有效，优先级高于本提示词的其他风格要求）】\n"
        + text
    )
