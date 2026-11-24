"""工具预算：只读工具去重、单工具上限、收敛提示。

`turn.py` 只负责发事件和执行工具；「同一个只读调用不要再跑、到第几次提醒收手」
放在这里，避免主循环继续变长。
"""
from __future__ import annotations

import json

# 只读工具：同名同参数重复调用没有意义，直接复用上一轮结果。
# run_code 有自己的防抖（见 turn._handle_tool_call），make_plan/写工具/web/OCR 不在此列。
READ_ONLY_DEDUPE = {
    "search_materials", "read_material", "search_records",
    "recent_wrong_items", "due_reviews", "list_vocab", "get_mastery",
    "get_train_summary", "today_summary", "get_cet6_context",
    "search_local_files", "read_local_file", "list_recordings",
    "search_dialog_archive",
}
# 次数上限只防「换关键词乱搜」，不卡合法的资料分段；P35.1 的资料题用了 4 次搜索。
TOOL_LIMITS = {"search_materials": 5, "read_material": 5}

HINT_THRESHOLDS = (3, 6)

HINT_TEXT = ("【工具预算】本轮已调用 {count} 次工具。同一查询/同一资料不要重复调用；"
             "优先用已有搜索结果里的资料 id/页码去 read_material；"
             "证据够就直接回答并引用来源，不够就明说缺什么，不要再换关键词反复搜。")


def note_readonly(state, name: str, tool_input) -> str:
    """登记一次只读调用；返回非空字符串表示这次应该跳过（原因）。"""
    if name not in READ_ONLY_DEDUPE:
        return ""
    signature = (name, json.dumps(tool_input or {}, sort_keys=True,
                                  ensure_ascii=False, default=str))
    attempts = state.tool_attempts.get(name, 0)
    limit = TOOL_LIMITS.get(name, 0)
    if signature in state.tool_seen:
        return ("这次调用和本轮之前完全相同，结果不会变；不要重复调用，"
                "直接用已有结果回答。")
    if limit and attempts >= limit:
        return (f"本轮已经调用 {name} {attempts} 次，到了检索预算；"
                "基于已有结果回答，并说明还缺什么。")
    state.tool_seen.add(signature)
    if limit:
        state.tool_attempts[name] = attempts + 1
    return ""


def budget_hint(turn) -> str:
    """3 次 / 6 次各提醒一次；代码调试跳过，避免诱导未验证回答。"""
    if turn.code_debug:
        return ""
    if not str(getattr(turn.request, "profile", "") or "").startswith("assistant"):
        return ""
    state = turn.state
    for threshold in HINT_THRESHOLDS:
        if state.tool_calls >= threshold and threshold not in state.convergence_hinted:
            state.convergence_hinted.add(threshold)
            return HINT_TEXT.format(count=state.tool_calls)
    return ""
