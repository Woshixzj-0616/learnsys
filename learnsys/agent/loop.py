"""Agent 循环：看图 → 组装上下文 → 流式回答 → 需要时调工具 → 再回答。

界面只跟 `run()` 打交道；模型协议在 `provider_anthropic` 里，工具在 `tools` 里，
提示词在 `prompts` 里。三块都可以单独测。
"""
from __future__ import annotations

import dataclasses
import pathlib
import threading
from collections.abc import Iterator

from learnsys.agent import budget, debug_intent, memory, prompts, router, tools, vision
from learnsys.llm.config import AgentConfig, load_config
from learnsys.agent.events import AgentEvent
from learnsys.llm.provider_anthropic import ProviderError
from learnsys.agent.turn import (
    AgentError,
    AgentRequest,
    _finish,
    _retry_thinking_only,
    _RunState,
    _run_tool_loop,
    _Turn,
)

MAX_TOOL_STEPS = 8


def _read_profile(cfg: AgentConfig) -> str:
    """学习档案是可选的：没有就是空串，不让它拦住问答。"""
    try:
        if cfg.profile_path.exists():
            return cfg.profile_path.read_text(encoding="utf-8", errors="replace")[:2000]
    except Exception:
        pass
    return ""


def _history_messages(history: list[tuple[str, str]] | None,
                      image_text: str) -> list[dict]:
    """把「问/答」对变成 Anthropic 消息；图和它的转述只挂第一轮。

    上限 8 轮（有会话摘要时才会喂到这么多；没有摘要调用方仍只给 4 轮）：
    保留第一轮（图挂在那儿）+ 最近七轮。
    """
    turns = [(str(q), str(a)) for q, a in (history or []) if q]
    if not turns:
        return []
    if len(turns) > 8:
        turns = [turns[0]] + turns[-7:]
    messages: list[dict] = []
    for index, (question, answer) in enumerate(turns):
        if index == 0 and image_text.strip():
            question = ("【这张截图的内容（视觉转述/OCR，供追问参考）】\n"
                        + image_text.strip()[:4000]
                        + "\n\n【当时的问题】\n" + question)
        messages.append({"role": "user", "content": [{"type": "text", "text": question}]})
        messages.append({"role": "assistant",
                         "content": [{"type": "text", "text": answer}]})
    return messages


def _tool_context(request: AgentRequest, cfg: AgentConfig,
                  code_debug: bool = False) -> tools.ToolContext:
    return tools.ToolContext(
        data_root=pathlib.Path(cfg.data_root),
        db_path=pathlib.Path(cfg.data_root) / "learning.db",
        attachment_name=request.attachment_name,
        attachment_text=request.attachment_text,
        conversation_id=request.conversation_id,
        conversation_key=request.conversation_key,
        mode=request.mode,
        material_id=request.material_id,
        code_debug=code_debug,
    )


def _default_provider():
    from learnsys.llm import provider_anthropic
    return provider_anthropic


def _plan_config(cfg: AgentConfig, request: AgentRequest) -> tuple[AgentConfig, bool, router.RouteDecision]:
    """定这一轮的模型 / 思考 / 提示词档，并把决策原样带出来写流水。

    规则全部在 `agent/router.py`（单一落点）：手动速度档 > 手动 routes > 自动路由。
    """
    decision = router.decide(
        cfg, mode=request.mode, message=request.message, context=request.context,
        attachment_text=request.attachment_text,
        history_len=len(request.history or []),
        has_image=bool(request.image_path or request.extra_images))
    return router.apply(cfg, decision), decision.concise, decision


def _speed_config(cfg: AgentConfig, mode: str) -> tuple[AgentConfig, bool]:
    """兼容旧调用：只按模式取档位，返回 (配置, 是否用精简提示词)。"""
    decision = router.decide(cfg, mode=mode)
    return router.apply(cfg, decision), decision.concise


def _prepare(request: AgentRequest, cfg: AgentConfig, provider, abort):
    """就绪/中止检查 → 路由 → 档案/记忆/看图 → 提示词与消息。

    返回 `_Turn`；返回 None 表示已经发过终止事件（error / aborted），调用方直接结束。
    """
    if not cfg.ready:
        yield AgentEvent("error", text=(
            "还没配置模型。打开「设置」，填一个 Anthropic / OpenAI 兼容服务的地址和密钥；"
            "也可以先在 D:/学习系统/设置.json 里填 agent.base_url、agent.auth_token、agent.model。"))
        return None
    if abort is not None and abort.is_set():
        yield AgentEvent("done", data={"text": "", "stop_reason": "aborted"})
        return None

    blocked = budget.check(cfg)
    if blocked:
        yield AgentEvent("error", text=blocked)
        return None

    # 代码调试只在「能跑代码」的入口生效（工作台问答页、非测验、非 system_override）。
    intent = debug_intent.detect(request.message)
    code_debug = bool(
        intent["code_debug"] and request.use_tools and not request.system_override
        and request.surface == "ask" and request.mode != "quiz")
    if code_debug:
        # 立刻给界面一句具体状态：用户不用盯着「思考中」猜在干什么。
        yield AgentEvent("activity",
                         text="代码调试：先编译运行验证，再回答（通常 10–30 秒）")

    provider = provider or _default_provider()
    cfg, concise, decision = _plan_config(cfg, request)
    forced_debug = False
    if code_debug and (cfg.speed or "").lower() == "balanced" and decision.tier != "manual":
        # 实测：不思考 + 强制运行会反复构造错输入、8 次超时；代码调试必须开思考。
        # 只覆盖默认 balanced；用户手动选 fast / deep 或配了 routes，就尊重用户。
        if not cfg.thinking:
            cfg = dataclasses.replace(cfg, thinking=True)
            forced_debug = True
            concise = False
            decision = dataclasses.replace(
                decision, thinking=True, concise=False,
                reason=(decision.reason or "") + "；代码调试强制思考")
    cfg_holder = [cfg]
    if (cfg.auto_route or "off").lower() in ("shadow", "on"):
        route_data = decision.trace()
        route_data["auto"] = cfg.auto_route
        if forced_debug:
            route_data["forced"] = "code_debug"
        yield AgentEvent("route", data=route_data)

    profile = _read_profile(cfg)
    memory_text = memory.render_for_prompt(cfg.data_root)
    image_paths = ([request.image_path] if request.image_path else []) + list(
        request.extra_images or [])
    image_text = ""
    used_vision = False
    if image_paths:
        yield AgentEvent("vision", text="正在看截图…", data={"count": len(image_paths)})
        try:
            image_text, used_vision = vision.describe_images(image_paths, cfg, abort=abort)
        except Exception as exc:
            image_text = f"（图片转述失败：{exc}）"
            used_vision = False
        yield AgentEvent("vision", data={"used_vision": used_vision,
                                        "count": len(image_paths)})
    if abort is not None and abort.is_set():
        yield AgentEvent("done", data={"text": "", "stop_reason": "aborted"})
        return None

    system = (request.system_override.strip()
              or prompts.build_system(request.mode, has_image=bool(image_paths),
                                      profile=profile, memories=memory_text,
                                      summary=request.history_summary,
                                      code_debug=code_debug,
                                      concise=concise))
    tool_schemas = tools.schemas_for(request.mode, use_tools=request.use_tools,
                                     surface=request.surface)
    messages = _history_messages(request.history, image_text)
    current_text = prompts.build_user_text(
        request.message,
        context=request.context,
        context_title=request.context_title,
        image_text="" if messages else image_text,
        image_used_vision=used_vision,
        attachment_name=request.attachment_name,
        attachment_text=request.attachment_text,
    )
    messages.append({"role": "user", "content": [{"type": "text", "text": current_text}]})

    return _Turn(
        request=request,
        provider=provider,
        cfg_holder=cfg_holder,
        system=system,
        tool_schemas=tool_schemas,
        messages=messages,
        state=_RunState(),
        ctx=_tool_context(request, cfg, code_debug),
        image_paths=image_paths,
        used_vision=used_vision,
        code_debug=code_debug,
    )


def run(request: AgentRequest, *, provider=None, cfg: AgentConfig | None = None,
        abort: threading.Event | None = None,
        response_sink: list | None = None,
        max_steps: int = MAX_TOOL_STEPS,
        confirm=None) -> Iterator[AgentEvent]:
    """跑一轮 Agent，边跑边 yield 事件。失败只发 error，不抛给界面。

    `confirm(request_id, tool_name, args) -> bool` 是写操作的人肉闸门：
    没传（或返回 False）就不执行，并把「用户没确认」作为工具结果回给模型。
    """
    cfg = cfg or load_config()
    turn = yield from _prepare(request, cfg, provider, abort)
    if turn is None:
        return
    try:
        if not (yield from _run_tool_loop(
                turn, abort=abort, response_sink=response_sink,
                max_steps=max_steps, confirm=confirm)):
            return
        yield from _retry_thinking_only(turn, abort=abort,
                                        response_sink=response_sink)
        yield from _finish(turn, abort=abort)
    except ProviderError as exc:
        yield AgentEvent("error", text=str(exc))
    except AgentError as exc:
        yield AgentEvent("error", text=str(exc))
    except Exception as exc:           # 兜底：后台异常不能把界面搞死
        yield AgentEvent("error", text=f"Agent 出错了：{exc}")
