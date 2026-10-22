"""计划：把模型给出的步骤规范化，并跟踪每一步的状态。

只有一份真实来源：loop 里的 `state.plan`。事件、界面、流水都从它派生，
不另存一份「进度」。
"""
from __future__ import annotations

MAX_STEPS = 6
_STATUSES = {"pending", "doing", "done", "failed", "skipped"}


def normalize_steps(raw) -> tuple[list[dict], bool]:
    """把模型的 `steps` 参数变成内部步骤；返回 (步骤, 是否被截断)。

    兼容三种写法：字符串、{"title": ...}、{"step": ...}。
    空标题丢弃；最多 MAX_STEPS 步，多出来的明确告诉模型被截断。
    """
    if not isinstance(raw, list):
        return [], False
    steps: list[dict] = []
    truncated = False
    for item in raw:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("step") or "").strip()
            tool = str(item.get("tool") or "").strip()
        else:
            title = str(item or "").strip()
            tool = ""
        if not title:
            continue
        if len(steps) >= MAX_STEPS:
            truncated = True
            break
        steps.append({
            "index": len(steps),
            "title": title[:120],
            "tool": tool[:40],
            "status": "pending",
        })
    return steps, truncated


def match_step(steps: list[dict], tool: str) -> int | None:
    """工具调用落到哪一步：第一个还没结束、且声明了这个工具的步骤。"""
    name = str(tool or "").strip()
    if not name:
        return None
    for step in steps:
        if step.get("tool") == name and step.get("status") in ("pending", "doing"):
            return int(step["index"])
    return None


def mark_step(steps: list[dict], index: int | None, status: str) -> bool:
    """改一步的状态；返回是否真的改了（界面据此决定要不要发 plan_update）。"""
    if index is None or status not in _STATUSES:
        return False
    try:
        step = steps[int(index)]
    except (IndexError, TypeError, ValueError):
        return False
    if step.get("status") == status:
        return False
    step["status"] = status
    return True


def summary_text(steps: list[dict]) -> str:
    """给模型看的一行计划摘要。"""
    if not steps:
        return "（计划为空）"
    return "；".join(f"{index + 1}. {step['title']}"
                    for index, step in enumerate(steps))
