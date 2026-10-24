"""模型接入基础层：配置读取 + Anthropic Messages 协议客户端。

放在 `agent` 之外：`agent`（对话）和 `services`（翻译 / 分析 / 解释）是平级包，
两边都要用模型配置与协议客户端；如果留在 `agent` 里，`services → agent` 会和
`agent → services` 形成包级双向依赖。这里只依赖标准库与 `learnsys.config`。
"""
from __future__ import annotations

from .config import AgentConfig, load_config

__all__ = ["AgentConfig", "load_config"]
