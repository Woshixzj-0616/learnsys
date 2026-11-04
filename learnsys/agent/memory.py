"""Agent 的长期记忆：读给系统提示词，工具负责写。

记忆只有一份 —— `learning.db` 的 `agent_memories` 表：
- Agent 用 `save_memory` / `forget_memory` 改它；
- 每轮按「硬规矩 → 当前场景 → 相关偏好」挑选，带预算拼进系统提示词；
- 设置页也能看、改、删（同一张表，不另存一份文本）。

约束：**一条 = 一条独立、可长期生效的规矩/偏好**。临时任务细节不进来。
"""
from __future__ import annotations

import datetime as dt
import math
import pathlib
import re

from learnsys import store

RULE_KINDS = ("rule", "constraint")
PROFILE_KINDS = ("identity", "goal", "constraint")
NEGATION_WORDS = ("不要", "别", "禁止", "无需", "避免", "不")
DEFAULT_LIMIT = 12
DEFAULT_CHARS = 1600
PINNED_ITEMS = 5
PINNED_CHARS = 600
EMPTY_MEMORY_TEXT = (
    "【用户长期记忆】\n"
    "（目前还没有与本轮相关的记录。用户一旦提出跨会话的偏好或规矩，"
    "先调用 save_memory 记下来，再回答。）")


def db_path(data_root) -> pathlib.Path:
    return pathlib.Path(data_root or "") / "learning.db"


# 这些二元组几乎每句话都有，不能算「相关」。
STOP_BIGRAMS = {
    "怎么", "什么", "如何", "一下", "可以", "一个", "这个", "那个",
    "我们", "你的", "我的", "就是", "不是", "没有", "时候", "现在",
    "需要", "希望", "用户", "助手", "回答", "问题", "理解", "知道",
    "觉得", "还是", "这样", "那样", "比较", "帮助", "解释", "告诉",
}


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"[\s\W_]+", "", str(text or "").lower(), flags=re.UNICODE)
    return {compact[index:index + 2] for index in range(len(compact) - 1)
            if compact[index:index + 2] not in STOP_BIGRAMS}


def _overlap(query: str, content: str) -> float:
    left, right = _bigrams(query), _bigrams(content)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _recency(updated_at: str) -> float:
    try:
        moment = dt.datetime.strptime(str(updated_at or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0.0
    days = max(0.0, (dt.datetime.now() - moment).total_seconds() / 86400)
    return math.exp(-days / 90.0)


def _negated(text: str) -> bool:
    return any(word in str(text or "") for word in NEGATION_WORDS)


def _score(item: dict, query: str, hints: set[str]) -> float:
    scope = str(item.get("scope") or "global")
    if scope in hints:
        scope_score = 3.0
    elif scope == "global":
        scope_score = 0.5
    else:
        scope_score = 0.0
    overlap = _overlap(query, item.get("content") or "")
    rule_score = 0.3 if item.get("kind") in RULE_KINDS else 0.0
    score = (3.0 * scope_score + rule_score
             + float(item.get("confidence") or 0)
             + 2.0 * overlap
             + 0.5 * _recency(item.get("updated_at") or "")
             + 0.02 * min(int(item.get("use_count") or 0), 5))
    # 与本轮无关的工作类规矩别靠「高置信度」挤掉学习偏好。
    if (not item.get("pinned") and item.get("kind") in RULE_KINDS
            and overlap < 0.05):
        score -= 1.0
    # 低重合的全局偏好不该占学习问题的预算；完全无关的直接沉底。
    if not item.get("pinned") and scope not in hints:
        if overlap < 0.1:
            score -= 2.0
        if overlap == 0:
            score -= 0.5
    return score


def _suppress(items: list[dict]) -> tuple[list[dict], list[int]]:
    """近重复且一条含否定词时，压制较低分的那条。"""
    kept: list[dict] = []
    dropped: list[int] = []
    for item in items:
        conflict = None
        for other in kept:
            if _negated(item["content"]) == _negated(other["content"]):
                continue
            if _overlap(item["content"], other["content"]) > 0.6:
                conflict = other
                break
        if conflict is None:
            kept.append(item)
        else:
            dropped.append(int(item["id"]))
    return kept, dropped


def select_for_prompt(data_root, *, query: str = "", context: str = "",
                      scope_hints=(), limit: int = DEFAULT_LIMIT,
                      max_chars: int = DEFAULT_CHARS) -> dict:
    """按作用域、词面相关度、置信度和新鲜度挑记忆；返回选中项与审计信息。"""
    empty = {"items": [], "ids": [], "chars": 0, "suppressed": [],
             "scopes": [], "budget": {"items": limit, "chars": max_chars}}
    try:
        conn = store.connect(db_path(data_root))
    except Exception:
        return empty
    try:
        items = [item for item in store.list_memories(
            conn, limit=500, status="active")
            if item.get("kind") not in PROFILE_KINDS]
        hints = {str(item) for item in scope_hints if item}
        search = f"{query}\n{context}"
        # 只有显式钉住的回答铁律才每轮必带；普通 rule 也按相关度竞争，
        # 否则「多 agent 协作」这类工作规则会挤掉学习偏好。
        pinned = [item for item in items
                  if item.get("pinned")
                  and str(item.get("scope") or "global") in ({"global"} | hints)]
        rest = [item for item in items if item not in pinned]
        pinned.sort(key=lambda item: (float(item.get("confidence") or 0),
                                      item.get("updated_at") or ""),
                    reverse=True)
        chosen: list[dict] = []
        used = 0
        for item in pinned:
            line = len(item["content"]) + 40
            if len(chosen) >= PINNED_ITEMS or used + line > PINNED_CHARS:
                break
            chosen.append(item)
            used += line
        ranked = []
        for item in rest:
            scope = str(item.get("scope") or "global")
            overlap = _overlap(search, item.get("content") or "")
            if scope not in hints and scope != "global" and overlap < 0.15:
                continue
            ranked.append((_score(item, search, hints), item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        ranked_items = [item for score_value, item in ranked
                        if score_value >= 1.0]
        ranked_items, dropped = _suppress(ranked_items)
        for item in ranked_items:
            line = len(item["content"]) + 40
            if len(chosen) >= max(1, int(limit)) or used + line > max_chars:
                break
            chosen.append(item)
            used += line
        ids = [int(item["id"]) for item in chosen]
        try:
            store.mark_used(conn, ids)
        except Exception:
            pass
        return {
            "items": chosen, "ids": ids, "chars": used,
            "suppressed": dropped, "scopes": sorted({
                str(item.get("scope") or "global") for item in chosen}),
            "budget": {"items": limit, "chars": max_chars},
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def render_selection(selection: dict) -> str:
    items = selection.get("items") or []
    if not items:
        return ""
    lines = ["【用户长期记忆（跨会话有效；按「硬规矩 > 当前场景 > 全局偏好」排序）】"]
    for item in items:
        label = (f"- [#{item['id']}][{item.get('kind') or 'preference'}]"
                 f"[{item.get('scope') or 'global'}][{float(item.get('confidence') or 0):.2f}] "
                 f"{item['content']}")
        lines.append(label)
    lines.append("（未列出的不是不存在，只是与本轮无关。）")
    return "\n".join(lines)


def load_for_prompt(data_root, *, limit: int = 50, max_chars: int = 4000) -> str:
    """兼容旧调用：按 id 取前 N 条（新代码请用 select_for_prompt）。"""
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


def render_for_prompt(data_root, *, query: str = "", context: str = "",
                      scope_hints=(), limit: int = DEFAULT_LIMIT,
                      max_chars: int = DEFAULT_CHARS) -> str:
    # 没有本轮问题时（旧调用 / 工具预览）退回按 id 取前 N 条，保持旧行为。
    if not str(query or "").strip():
        loaded = load_for_prompt(data_root, limit=limit, max_chars=max_chars)
        if loaded:
            return "【用户长期记忆（跨会话有效）】\n" + loaded
        return EMPTY_MEMORY_TEXT
    selection = select_for_prompt(
        data_root, query=query, context=context, scope_hints=scope_hints,
        limit=limit, max_chars=max_chars)
    return render_selection(selection) or EMPTY_MEMORY_TEXT


def render_profile_for_prompt(data_root, *, max_chars: int = 1200) -> str:
    """身份/目标/约束的稳定画像；每轮从库现算，不读文件。"""
    try:
        conn = store.connect(db_path(data_root))
    except Exception:
        return ""
    try:
        items = store.list_memories(
            conn, limit=200, status="active", kinds=PROFILE_KINDS)
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # 预算有限：先放置信度高、句子短的，长篇环境笔记放最后再截断。
    items.sort(key=lambda item: (-float(item.get("confidence") or 0),
                                 len(item.get("content") or ""),
                                 item.get("updated_at") or ""))
    lines: list[str] = []
    total = 0
    for item in items:
        line = f"- {item['content']}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
