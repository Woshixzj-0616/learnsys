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

LIFE_ITEMS_SCHEMA = {
    "name": "life_items",
    "description": (
        "看用户生活事务箱里的待办：标题、类型（待办/作息记录/备注）、到期日、"
        "状态和备注。用户问「我有什么待办」「今天要做什么」时使用；只读，不改状态。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string",
                       "enum": ["open", "done", "archived", "all"],
                       "description": "默认 open（未完成）"},
            "limit": {"type": "integer", "description": "最多返回几条，默认 10"},
        },
    },
}
