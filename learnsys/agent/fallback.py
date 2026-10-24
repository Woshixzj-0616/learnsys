"""模型降级链：主模型不响应时退到轻量模型，再不行给中文的「现在能做什么」。

单独成模块是为了让 `loop.py` 只保留主循环；降级策略和主循环改动互不牵连。
"""
from __future__ import annotations

import dataclasses

from learnsys.llm.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.llm.provider_anthropic import ProviderError


def fallback_config(cfg: AgentConfig) -> AgentConfig | None:
    """主模型失败时可以退到哪一档；本来就是轻量模型就不退。"""
    if not cfg.fast_model or cfg.fast_model == cfg.model:
        return None
    return dataclasses.replace(cfg, model=cfg.fast_model, thinking=False)


def degraded_message(exc: Exception) -> str:
    return (
        f"模型服务这会儿不可用（{exc}）。主模型和轻量模型都试过了。\n"
        "现在可以：① 等一分钟再发一次；② 到「设置」检查地址和密钥；"
        "③ 先看本地资料库、错题本 —— 这些都存在本机，不依赖模型。")


def stream_with_fallback(provider, cfg_holder: list, system: str, messages: list,
                         tool_schemas, abort, response_sink):
    """流式调用模型；一个字都没吐出来就失败时，自动切轻量模型重试一次。

    已经输出部分文本再断的不重试 —— 重复内容比一句报错更糟。
    成功降级后把新配置写回 `cfg_holder`，同一轮后续工具步骤不再撞主模型。
    """
    emitted = False
    try:
        for event in provider.stream_messages(
                cfg_holder[0], system, messages, tool_schemas,
                abort=abort, response_sink=response_sink):
            if event.kind in ("text", "thinking"):
                emitted = True
            yield event
        return
    except ProviderError as exc:
        fallback = fallback_config(cfg_holder[0])
        if emitted or fallback is None:
            raise
        yield AgentEvent("activity",
                         text=f"主模型没响应（{exc}），改用轻量模型重试…")
        try:
            for event in provider.stream_messages(
                    fallback, system, messages, tool_schemas,
                    abort=abort, response_sink=response_sink):
                yield event
        except ProviderError as second:
            raise ProviderError(degraded_message(second)) from second
        finally:
            cfg_holder[0] = fallback
