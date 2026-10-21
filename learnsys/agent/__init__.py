"""学习工作台 · 独立 Agent。

不依赖 Codex、不依赖任何本地中转口：直接按 Anthropic Messages 协议
（或 OpenAI 兼容协议）说话。界面层只消费 `AgentEvent`，不关心底下是谁。
"""
from learnsys.agent.config import AgentConfig, load_config
from learnsys.agent.events import AgentEvent
from learnsys.agent.loop import AgentError, AgentRequest, run

__all__ = ["AgentConfig", "load_config", "AgentEvent", "AgentError", "AgentRequest", "run"]
