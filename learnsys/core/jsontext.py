"""模型 JSON 输出的容错解析（唯一落点）。

flash 常见三类坏输出：
1. 包了一层 Markdown 代码围栏；
2. 字符串里出现未转义的双引号（中文引号、题目原文）；
3. 字符串里有裸换行，或对象/数组尾逗号。

`parse_object()` 依次尝试：原样 → 截取首尾花括号 → 修复引号/换行 → 去尾逗号。
调用方：`services.analysis`（六级分析）、`train.review`（写作/翻译批改）。
"""
from __future__ import annotations

import json
import re


def repair_text(text: str) -> str:
    """修复字符串内未转义的引号与裸换行。"""
    out: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == '"':
            if not in_string:
                in_string = True
                out.append(char)
                continue
            # 字符串里的引号只有在后面跟着 , : } ] 或结束时才是收尾
            cursor = index + 1
            while cursor < len(text) and text[cursor] in " \t\r\n":
                cursor += 1
            following = text[cursor] if cursor < len(text) else ""
            if following in (",", ":", "}", "]", ""):
                in_string = False
                out.append(char)
            else:
                out.append('\\"')
            continue
        if in_string and char in "\r\n":
            out.append("\\n")
            continue
        out.append(char)
    return "".join(out)


def parse_object(text: str) -> dict:
    """从模型输出里取出一个 JSON 对象；失败抛 ValueError。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    left, right = text.find("{"), text.rfind("}")
    candidates = [text]
    if left >= 0 and right > left:
        candidates.append(text[left:right + 1])
    candidates.append(repair_text(candidates[-1]))
    candidates.append(re.sub(r",\s*([}\]])", r"\1", candidates[-1]))
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate, strict=False)
        except Exception as exc:  # noqa: BLE001 - 汇总成一条错误
            last_error = exc
            continue
        if isinstance(data, dict):
            return data
        last_error = ValueError("顶层不是 JSON 对象")
    raise ValueError(f"模型输出里没有可解析的 JSON：{last_error}")
