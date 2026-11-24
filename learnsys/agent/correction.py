"""用户纠正轮识别：只认「你答偏了 / 我说的不是这个」这类明确信号。

关键词只在这里维护一份：chat 路由用它决定本轮是否升强模型，快捷栏也复用。
普通反问（「这样不对吗？」）不算纠正，避免把正常追问误升级。
"""
from __future__ import annotations

import re

_STRONG = (
    "我说的是", "我问的是", "不是问", "不是这个意思", "你理解错",
    "理解错了", "答非所问", "跑题", "答偏", "听不懂", "没听懂",
    "你没回答", "你答的不是", "不是我问的",
)
_SOFT = (
    re.compile(r"^不对[，,。！!\s]"),
    re.compile(r"你[^。！？\n]{0,6}不对[。！!]"),
)


def detect(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    if any(word in text for word in _STRONG):
        return True
    return any(pattern.search(text) for pattern in _SOFT)
