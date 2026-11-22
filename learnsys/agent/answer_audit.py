"""答案改口检测（结构性、纯规则、不调模型）。

用途：快捷栏答完后扫一遍，发现「先给一个答案、后面又改口」时，
在答案底部给一个「深入复核」入口；只提示，不改写答案。

判据只读结构：
- 明确的自我纠正语句（我上面说错了 / 纠正一下 / 等一下……改为）；
- 同一答案里出现多个「答案选 X」槽位，且中间夹着纠正标记。
代码围栏、行内代码、引用块里的内容不算。
"""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*?`+")
_EXPLICIT_RE = re.compile(
    r"我(?:上面|刚才|前面)[^。！？\n]{0,30}(?:说错|写错|错了|不对|有误)"
    r"|(?:纠正|更正)一下"
    r"|说错了"
    r"|等一下[，,][^。！？\n]{0,40}(?:改为|应为|应是|其实是|说错)"
)
_OPTION_RE = re.compile(
    r"(?:答案|结论|应选|所以选|因此选|选)\s*(?:是|为|：|:)?\s*"
    r"\**\s*([A-D]|[一二三四])"
)
_MARK_RE = re.compile(r"等一下|纠正|更正|说错|改为|其实是")


def check(text: str) -> str:
    """命中返回原因（self_corrected / answer_changed），否则空串。"""
    body = _answer_body(text)
    if not body.strip():
        return ""
    if _EXPLICIT_RE.search(body):
        return "self_corrected"
    values = [(match.start(), match.group(1)) for match in _OPTION_RE.finditer(body)]
    if len({value for _, value in values}) < 2:
        return ""
    first, last = values[0][0], values[-1][0]
    if _MARK_RE.search(body, first, last + 1):
        return "answer_changed"
    return ""


def _answer_body(text: str) -> str:
    """去掉代码围栏、行内代码、引用块，避免把题目原文当成答案改口。"""
    lines: list[str] = []
    fence = ""
    for line in str(text or "").splitlines():
        stripped = line.lstrip()
        hit = _FENCE_RE.match(stripped)
        if fence:
            if hit and hit.group(1)[0] == fence:
                fence = ""
            continue
        if hit:
            fence = hit.group(1)[0]
            continue
        if stripped.startswith(">"):
            continue
        lines.append(line)
    return _INLINE_CODE_RE.sub("", "\n".join(lines))
