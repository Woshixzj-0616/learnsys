"""模型降级链：主模型不响应时退到轻量模型，再不行给中文的「现在能做什么」。

断流策略（2026-11-03 P31 · M3 起）：
- **没出字**就断 → 沿用原降级：切轻量模型重试一次，仍失败给中文提示；
- **出过字**再断 → 最多续写一次：把已写内容作为 assistant 消息发回去，
  请求「从中断处继续，不要重复」；续写不带工具，避免半截 tool_use；
- 续写再失败就抛错，已经流出的正文由 chat.py 照常落库（partial + interrupted）。
- 已出字是否允许续写由 `claim_audit` 开关控制；字数为 0 时绝不续写。

单独成模块是为了让 `loop.py` 只保留主循环；降级策略和主循环改动互不牵连。
"""
from __future__ import annotations

import dataclasses

from learnsys.llm.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.llm.provider_anthropic import ProviderError

CONTINUE_PROMPT = ("请从中断处继续，不要重复已经写过的内容；"
                   "如果已经答完，只回复「已完成」。")


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
    """流式调用模型；断流时按「有没有出过字」分流降级或续写。"""
    parts: list[str] = []
    try:
        for event in provider.stream_messages(
                cfg_holder[0], system, messages, tool_schemas,
                abort=abort, response_sink=response_sink):
            if event.kind == "text":
                parts.append(event.text or "")
            yield event
        return
    except ProviderError as exc:
        if not parts:
            fallback = fallback_config(cfg_holder[0])
            if fallback is None:
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
            return

        if not getattr(cfg_holder[0], "claim_audit", True):
            raise
        yield AgentEvent("activity", text="模型流断了，正在从中断处续写…",
                         data={"retry": 1})
        messages2 = list(messages) + [
            {"role": "assistant",
             "content": [{"type": "text", "text": "".join(parts)}]},
            {"role": "user",
             "content": [{"type": "text", "text": CONTINUE_PROMPT}]},
        ]
        # 最多续写一次；tools=None —— 半截工具调用没法安全重放。
        for event in provider.stream_messages(
                cfg_holder[0], system, messages2, None,
                abort=abort, response_sink=response_sink):
            if event.kind == "text":
                parts.append(event.text or "")
                yield event
            elif event.kind == "done":
                merged = dataclasses.replace(event.result, text="".join(parts))
                yield dataclasses.replace(event, result=merged)
            else:
                yield event
