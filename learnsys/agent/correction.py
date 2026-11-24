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


# 用户否定前提：只影响本轮提示词（强制写「已排除」），不升强模型。
# 比 detect 宽一点：用户不会每次都喊「你答偏了」，更多是「我没写过 / 不是靶机」。
_NEGATION = (
    re.compile(r"我[^，。！？\n]{0,4}没(有|写过|做过|说过|弄过)"),
    re.compile(r"我不(会|用|需要)"),
    re.compile(r"不是(我|这个|那个|它)"),
    re.compile(r"不是[^，。！？\n]{1,6}(机|器|平台|环境)"),
    re.compile(r"都和你说了|说了没有|说了不是|你听不懂"),
)


def negation(message: str) -> bool:
    """这句是不是在否定前文的前提（我没写过 / 不是靶机 / 都和你说了没有）。"""
    text = str(message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _NEGATION)


def exclusions(history, message: str = "", limit: int = 4) -> list[str]:
    """把用户否定过的原话摘出来，注入本轮提示。

    不让模型自己从长历史里「记得」排除项：直接把原话摆到它面前。
    只取最近几条，避免提示词膨胀。
    """
    texts = [str(question or "") for question, _answer in (history or [])]
    texts.append(str(message or ""))
    found: list[str] = []
    for text in texts:
        for sentence in re.split(r"[。！？!?\n]", text):
            piece = sentence.strip()
            if piece and negation(piece) and piece not in found:
                found.append(piece[:60])
    return found[-max(1, int(limit)):]
