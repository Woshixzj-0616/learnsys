"""智能旅行 trace 工具 schema（为 `schemas.py` 体量红线单独放）。"""
from __future__ import annotations

TRAVEL_TRACE_SCHEMA = {
    "name": "travel_trace",
    "description": (
        "只读查询智能旅行 agent 的调用路径（trace）：最近请求、哪条最慢、"
        "某条请求各段耗时 / 工具 / 打回次数。用户问「智能旅行最近哪条慢」"
        "「这条请求怎么走的」时使用；不修改旅行数据，也不需要登录。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer",
                      "description": "最近几条，默认 10，最多 30"},
            "trace_id": {"type": "string",
                         "description": "指定 trace 编号看详情；留空看最近列表"},
            "slow_only": {"type": "boolean",
                          "description": "只看最慢的几条"},
        },
    },
}
