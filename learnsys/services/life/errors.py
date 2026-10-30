"""生活订阅的两种可预期失败。

单独成文件，避免 `cards.py` 与 `stock.py` 互相导入。
"""
from __future__ import annotations


class LifeNotReady(ValueError):
    """前置资料还没准备好（例如当天简报未生成）：下个 tick 再试，不记时间。"""


class LifeUnsupported(ValueError):
    """当前类型/配置不支持：按「已处理」记一次，不反复重试。"""
