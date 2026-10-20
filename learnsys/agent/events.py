"""Agent 对外的统一事件。

界面只认这几种 kind：
- thinking   模型在推理（只更新「思考中」提示，不进正文）
- text       正文增量（直接往答案区追加）
- vision     图片转述完成（data.used_vision 表示真看了图还是只 OCR）
- tool_start 开始查本地记录 / 读文档
- tool_end   工具返回（data.preview 是一句话摘要）
- done       本轮完成（data.text 是完整正文）
- error      失败（text 是能直接给人看的中文原因）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    kind: str
    text: str = ""
    data: dict = field(default_factory=dict)
