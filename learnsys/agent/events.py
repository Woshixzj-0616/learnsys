"""Agent 对外的统一事件。

界面只认这几种 kind：
- thinking   模型在推理（增量；界面可展示，但不算正文）
- activity   过程提示（如「只输出了思考，正在重试」）
- text       正文增量（直接往答案区追加）
- vision     图片转述完成（data.used_vision 表示真看了图还是只 OCR）
- plan       计划登记（data.steps = [{index,title,tool,status}]）
- plan_update 某一步状态变化（data.index / data.status / data.steps）
- tool_start 开始查本地记录 / 读文档（data.goal = 计划步骤标题，data.step = 步骤序号）
- tool_end   工具返回（data.preview 摘要，data.ok 是否成功，data.denied 写入被拒）
- confirm    写操作等待用户确认（data.request_id / tool / summary）
- check      自检结果（data.ok / data.issues / data.checked；重写后再发一次）
- rewrite    自检后重写的完整答案（data.text 替换当前正文，不是追加）
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
