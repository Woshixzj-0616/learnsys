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


def estimate(usage: dict | None, cfg) -> tuple[float, str, str]:
    """按设置里的单价估算成本；返回 (金额, 币种, 说明)。"""
    counts = normalize_usage(usage)
    price_in = float(getattr(cfg, "price_input", 0) or 0)
    price_out = float(getattr(cfg, "price_output", 0) or 0)
    price_cache = float(getattr(cfg, "price_cache_read", 0) or 0)
    if not (price_in or price_out or price_cache):
        return 0.0, "", "未配置单价"
    amount = (counts["uncached_tokens"] / 1_000_000 * price_in
              + counts["cache_write_tokens"] / 1_000_000 * price_in
              + counts["cache_read_tokens"] / 1_000_000 * price_cache
              + counts["completion_tokens"] / 1_000_000 * price_out)
    return round(amount, 6), str(getattr(cfg, "currency", "") or ""), ""
