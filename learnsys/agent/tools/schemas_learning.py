"""学习状态类只读工具的 schema：到期复习、掌握度、训练概况、录像列表。

单独成文件是为了让 `schemas.py` 留在 500 行红线内（体量门禁）。
"""
from __future__ import annotations

DUE_REVIEWS_SCHEMA = {
    "name": "due_reviews",
    "description": (
        "列出今天到期的错题和生词（FSRS 排期），带题目/单词、到期日和复习次数。"
        "用户问「今天该复习什么」「有哪些该复习的」时使用；引用错题写「错题 #编号」。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "最多返回几张，默认 20"},
            "item_type": {"type": "string", "enum": ["wrong", "vocab"],
                          "description": "只看到期错题或只看到期生词；留空 = 全部"},
        },
    },
}

GET_MASTERY_SCHEMA = {
    "name": "get_mastery",
    "description": (
        "读取知识点掌握度（BKT）：每个类目的掌握度、样本数、等级，以及最弱类目。"
        "用户问「我最弱的知识点」「我阅读/听力掌握得怎么样」「离掌握还差多少」时使用。"
        "样本不足 5 条的类目会明确标「样本不足」，不要把它当掌握。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer",
                     "description": "只统计最近多少天；0 = 全部历史（默认）"},
        },
    },
}

GET_TRAIN_SUMMARY_SCHEMA = {
    "name": "get_train_summary",
    "description": (
        "读取六级写作/翻译训练概况：连续天数、今天练了什么、到期错误卡、"
        "近 N 天的提交量、平均档位趋势和最常见的错误类型。"
        "用户问「我写作练得怎么样」「档位有没有提高」「今天训练任务是什么」时使用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "统计最近多少天，默认 30，范围 7–365"},
        },
    },
}

LIST_RECORDINGS_SCHEMA = {
    "name": "list_recordings",
    "description": (
        "列出本地录像：时间、标题、时长、转写段数、开头片段。可按转写文字筛选。"
        "用户问「我录过哪些课」「找一段讲 X 的录像」时使用；"
        "需要正文再用 search_records（kinds=transcripts）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "按转写文字筛选，可留空"},
            "limit": {"type": "integer", "description": "最多返回几段，默认 10"},
        },
    },
}
