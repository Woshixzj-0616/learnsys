"""创作库工具 schema（只读）：作品档案。"""
from __future__ import annotations

ART_WORKS_SCHEMA = {
    "name": "art_works",
    "description": (
        "看用户创作库里的作品档案：标题、风格预设、模型、日期和提示词摘要。"
        "用户问「我生成过哪些图」「上次用的提示词是什么」时使用；只读。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string",
                       "enum": ["active", "archived", "all"],
                       "description": "默认 active（未归档）"},
            "limit": {"type": "integer", "description": "最多返回几件，默认 10"},
        },
    },
}
