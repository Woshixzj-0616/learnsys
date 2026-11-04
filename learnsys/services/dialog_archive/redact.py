"""写入档案前的脱敏：邮箱、手机号、身份证、常见密钥与赋值。

只替换值，不删除整条消息；每类命中次数写进档案头部。
正则不能保证 100% 识别自由格式秘密，档案本身仍按敏感文件管理。
"""
from __future__ import annotations

import re

_RULES = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "[已脱敏:邮箱]"),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[已脱敏:手机号]"),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[已脱敏:身份证]"),
    ("api_key", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"), "[已脱敏:密钥]"),
    ("bearer", re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]{16,}"),
     "Bearer [已脱敏]"),
    ("password", re.compile(
        r"(?i)\b(password|passwd|pwd|api_key|apikey|secret|token)\b"
        r"\s*[:=]\s*[\"']?([^\s\"',;]{4,})"), None),
)

REDACT_RULES = tuple(name for name, _pattern, _repl in _RULES)


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """返回 `(脱敏后文本, 每类命中次数)`。"""
    counts: dict[str, int] = {}
    result = str(text or "")
    for name, pattern, replacement in _RULES:
        if name == "password":
            def keep_key(match: re.Match) -> str:
                counts[name] = counts.get(name, 0) + 1
                return f"{match.group(1)}=[已脱敏]"
            result = pattern.sub(keep_key, result)
            continue
        def swap(match: re.Match) -> str:
            counts[name] = counts.get(name, 0) + 1
            return replacement
        result = pattern.sub(swap, result)
    return result, counts


def total_counts(parts: list[dict[str, int]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for part in parts:
        for key, value in part.items():
            total[key] = total.get(key, 0) + int(value)
    return total
