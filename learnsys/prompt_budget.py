"""提示词 token 预算：估算、分配、裁剪的唯一落点。

为什么不用字符数：同一个 6000 字，中文约 6000 token、英文约 1700 token；
按字符截断会让中文 prompt 悄悄超预算，而英文 prompt 又浪费额度。

口径：
- 估算不依赖 tiktoken：中文字符 ≈ 1 token，其余字符 ≈ 1/3.5 token；
  刻意略高估，宁可早一点截断，也不让请求被服务端拒绝。
- 裁剪保留头尾（结论通常在头、报错/结果通常在尾），中间打标记；
- 分配按优先级：用户本轮问题不裁，其余按权重分剩余预算。

调用方：
- `agent/prompts.py`：系统提示词与用户消息的各段默认上限；
- `agent/loop.py`：本轮所有可变段共享一个输入预算 + 历史窗口；
- `agent/turn.py`：单次工具结果与整轮工具结果预算。
"""
from __future__ import annotations

import math
import re

# 输入预算（不含模型输出）。DeepSeek 上下文 128K，这里保守留 24K：
# 长会话真正危险的是工具结果堆叠，不是系统提示词。
DEFAULT_PROMPT_TOKENS = 24000
DEFAULT_TOOL_RESULT_TOKENS = 3000
DEFAULT_TOOL_TURN_TOKENS = 12000
DEFAULT_HISTORY_TOKENS = 6000
DEFAULT_HISTORY_ANSWER_TOKENS = 800

# 单段的默认上限（没走共享预算时用，保证直接调用也不会无界）。
SUMMARY_TOKENS = 900
PROFILE_TOKENS = 700
MEMORY_TOKENS = 1200
PERSONAL_STATE_TOKENS = 500
IMAGE_TOKENS = 2500
ATTACHMENT_TOKENS = 3000
CONTEXT_TOKENS = 1500

# 共享预算里的相对权重：用户问题最高，其次上下文/历史，最后附件。
DEFAULT_WEIGHTS = {
    "question": 100,
    "context": 45,
    "history": 50,
    "image_text": 35,
    "attachment": 25,
}
MIN_SECTION_TOKENS = 120

_CLIP_MARK = "\n…（已截断）"
_CJK_RE = re.compile(
    r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def estimate_tokens(text) -> int:
    """粗估 token 数；空串为 0，非空至少 1。"""
    value = str(text or "")
    if not value:
        return 0
    cjk = len(_CJK_RE.findall(value))
    other = len(value) - cjk
    return max(1, cjk + math.ceil(other / 3.5))


def estimate_messages(messages) -> int:
    """估一段 Anthropic messages 的 token（只数文本块和工具结果）。"""
    total = 0
    for message in messages or []:
        content = (message or {}).get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                total += estimate_tokens(block.get("text"))
            elif block.get("type") == "tool_result":
                item = block.get("content")
                if isinstance(item, str):
                    total += estimate_tokens(item)
                elif isinstance(item, list):
                    total += sum(estimate_tokens(x.get("text") if isinstance(x, dict) else x)
                                 for x in item)
    return total


def _cut_prefix(text: str, limit: int) -> str:
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _cut_suffix(text: str, limit: int) -> str:
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[-mid:]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[-lo:] if lo else ""


def clip_tokens(text, max_tokens: int, *, keep: str = "head_tail") -> str:
    """把文本裁到不超过 max_tokens；keep=head / tail / head_tail。"""
    value = str(text or "")
    limit = int(max_tokens or 0)
    if limit <= 0:
        return ""
    if estimate_tokens(value) <= limit:
        return value
    mark_tokens = estimate_tokens(_CLIP_MARK)
    budget = max(1, limit - mark_tokens)
    if keep == "head":
        return _cut_prefix(value, budget) + _CLIP_MARK
    if keep == "tail":
        return _CLIP_MARK + _cut_suffix(value, budget)
    head_budget = max(1, int(budget * 0.6))
    tail_budget = max(1, budget - head_budget)
    head = _cut_prefix(value, head_budget)
    tail = _cut_suffix(value, tail_budget)
    if len(head) + len(tail) >= len(value):
        return value
    return head + _CLIP_MARK + tail


def input_budget(cfg, default: int = DEFAULT_PROMPT_TOKENS) -> int:
    """本轮输入预算；配置为 0 / 负数时用默认值。"""
    value = int(getattr(cfg, "prompt_budget_tokens", 0) or 0)
    return value if value > 0 else default


def tool_result_budget(cfg, used_tokens: int, name: str = "") -> int:
    """这一次工具结果还能给多少 token；整轮用完时只留一小段。"""
    per = int(getattr(cfg, "tool_result_tokens", 0) or DEFAULT_TOOL_RESULT_TOKENS)
    total = int(getattr(cfg, "tool_turn_tokens", 0) or DEFAULT_TOOL_TURN_TOKENS)
    if str(name or "") == "run_code":
        per = max(per, 4000)          # 运行输出是证据，多留一点
    left = total - max(0, int(used_tokens or 0))
    return max(400, min(per, left))


def history_budget(cfg) -> int:
    value = int(getattr(cfg, "history_tokens", 0) or 0)
    return value if value > 0 else DEFAULT_HISTORY_TOKENS


def fit_sections(sections: dict, total_tokens: int, *, order=None,
                 weights: dict | None = None,
                 min_tokens: int = MIN_SECTION_TOKENS) -> tuple[dict, dict]:
    """按优先级把多段文本装进一个共享预算；返回 (裁后文本, 审计)。

    `question` 永远不裁：裁掉用户的问题等于答非所问。
    """
    order = list(order or sections.keys())
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    present = {key: str(sections.get(key) or "") for key in order
               if str(sections.get(key) or "").strip()}
    requested = {key: estimate_tokens(value) for key, value in present.items()}
    total_requested = sum(requested.values())
    audit = {
        "budget": int(total_tokens or 0),
        "requested": total_requested,
        "after": total_requested,
        "clipped": False,
        "sections": {key: {"before": tokens, "after": tokens, "clipped": False}
                     for key, tokens in requested.items()},
    }
    if total_tokens <= 0 or total_requested <= total_tokens:
        return {key: str(sections.get(key) or "") for key in sections}, audit

    # 用户问题先全额保留；剩下的按权重分。
    alloc: dict[str, int] = {}
    if "question" in requested:
        alloc["question"] = requested["question"]
    others = [key for key in present if key not in alloc]
    remaining = max(0, int(total_tokens) - sum(alloc.values()))
    weight_sum = sum(max(1, int(weights.get(key, 10))) for key in others) or 1
    for key in others:
        share = int(remaining * max(1, int(weights.get(key, 10))) / weight_sum)
        alloc[key] = max(1, min(requested[key], max(min_tokens, share)))

    # 没吃满自己额度的段，把余量还给还在超额的段（最多两轮）。
    for _ in range(2):
        unused = sum(max(0, alloc[key] - requested[key]) for key in others)
        if unused <= 0:
            break
        for key in others:
            alloc[key] = min(alloc[key], requested[key])
        hungry = [key for key in others if alloc[key] < requested[key]]
        if not hungry:
            break
        hungry_weight = sum(max(1, int(weights.get(key, 10))) for key in hungry) or 1
        for key in hungry:
            alloc[key] += int(unused * max(1, int(weights.get(key, 10)))
                              / hungry_weight)

    fitted = {key: str(sections.get(key) or "") for key in sections}
    after_total = 0
    for key, value in present.items():
        clipped = clip_tokens(value, alloc.get(key, requested[key]))
        fitted[key] = clipped
        after = estimate_tokens(clipped)
        after_total += after
        audit["sections"][key] = {
            "before": requested[key], "after": after,
            "clipped": clipped != value,
        }
    audit["after"] = after_total
    audit["clipped"] = any(item["clipped"] for item in audit["sections"].values())
    return fitted, audit
