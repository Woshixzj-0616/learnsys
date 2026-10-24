"""Token 归一化与成本估算。

只做一件事：把不同提供商的 usage 字段统一成四个数，再按用户填的单价估算。
单价没填就明确显示「未配置单价」，不猜、不写死可能过时的价格。
"""
from __future__ import annotations


def normalize_usage(usage: dict | None) -> dict:
    """统一 Anthropic / OpenAI 两种 usage 口径。

    - Anthropic：input_tokens 不含缓存；cache_read_input_tokens / cache_creation_input_tokens 另算。
    - OpenAI / DeepSeek：prompt_tokens 含缓存命中；prompt_cache_hit_tokens 是其中一部分。
    """
    usage = usage if isinstance(usage, dict) else {}
    prompt = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    completion = int(usage.get("output_tokens")
                     or usage.get("completion_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens")
                     or usage.get("prompt_cache_hit_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    openai_style = usage.get("prompt_tokens") is not None
    if openai_style:
        uncached = max(0, prompt - cache_read)
        total_prompt = prompt
    else:
        uncached = prompt
        total_prompt = prompt + cache_read + cache_write
    return {
        "prompt_tokens": total_prompt,
        "uncached_tokens": uncached,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "completion_tokens": completion,
        "total_tokens": total_prompt + completion,
    }


def price_for(cfg, model: str = "") -> tuple[float, float, float]:
    """按模型取单价（每 100 万 token）：(输入, 输出, 缓存命中)。

    先查 `agent.prices` 里的同名模型；没配或全 0 就用全局单价。
    全都没填时返回全 0，由调用方显示「未配置单价」——不猜价格。
    """
    table = getattr(cfg, "prices", None)
    entry = table.get(str(model or "")) if isinstance(table, dict) and model else None
    if isinstance(entry, dict):
        values = (float(entry.get("input", 0) or 0),
                  float(entry.get("output", 0) or 0),
                  float(entry.get("cache_read", 0) or 0))
        if any(values):
            return values
    return (float(getattr(cfg, "price_input", 0) or 0),
            float(getattr(cfg, "price_output", 0) or 0),
            float(getattr(cfg, "price_cache_read", 0) or 0))


def estimate(usage: dict | None, cfg, model: str = "") -> tuple[float, str, str]:
    """按模型单价估算一次调用的成本；返回 (金额, 币种, 说明)。"""
    counts = normalize_usage(usage)
    price_in, price_out, price_cache = price_for(cfg, model)
    if not (price_in or price_out or price_cache):
        return 0.0, "", "未配置单价"
    amount = (counts["uncached_tokens"] / 1_000_000 * price_in
              + counts["cache_write_tokens"] / 1_000_000 * price_in
              + counts["cache_read_tokens"] / 1_000_000 * price_cache
              + counts["completion_tokens"] / 1_000_000 * price_out)
    return round(amount, 6), str(getattr(cfg, "currency", "") or ""), ""


def estimate_by_model(by_model: dict | None, cfg) -> tuple[float, str, bool]:
    """把「模型 → usage」逐模型估值；返回 (总额, 币种, 是否至少配了一个单价)。

    一次运行里可能混用主模型 / 强模型 / 降级模型，合并后的 usage 没法按一个
    单价算，所以账本按模型分开记、这里分开算。
    """
    total = 0.0
    configured = False
    for model, usage in (by_model or {}).items():
        amount, _, note = estimate(usage, cfg, model)
        total += amount
        configured = configured or not note
    return round(total, 6), str(getattr(cfg, "currency", "") or ""), configured
