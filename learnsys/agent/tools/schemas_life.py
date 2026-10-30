"""生活域工具 schema（只读）：订阅卡片。"""
from __future__ import annotations

LIFE_CARDS_SCHEMA = {
    "name": "life_cards",
    "description": (
        "看用户生活域的订阅卡片（新闻主题、每日一词、自定义订阅）的标题与摘要。"
        "用户问「今天订阅推了什么」「生活卡片里有什么」时使用；只读，不生成新卡片。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "最近几天，默认 1（今天）"},
            "limit": {"type": "integer", "description": "最多返回几张，默认 10"},
        },
    },
}
