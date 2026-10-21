"""Agent 循环：看图 → 组装上下文 → 流式回答 → 需要时调工具 → 再回答。

界面只跟 `run()` 打交道；模型协议在 `provider_anthropic` 里，工具在 `tools` 里，
提示词在 `prompts` 里。三块都可以单独测。
"""
from __future__ import annotations

import pathlib
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

from learnsys.agent import prompts, tools, vision
from learnsys.agent.config import AgentConfig, load_config
from learnsys.agent.events import AgentEvent
from learnsys.agent.provider_anthropic import ProviderError, ProviderResult

MAX_TOOL_STEPS = 8


class AgentError(Exception):
    """Agent 失败 —— 消息是能直接给人看的中文。"""


@dataclass
class AgentRequest:
    message: str
    history: list[tuple[str, str]] | None = None
    image_path: str | None = None
    extra_images: list[str] | None = None
    context: str = ""
    context_title: str = ""          # 上下文标题（六级传「当前学习上下文」）
    attachment_name: str = ""
    attachment_text: str = ""
    mode: str = "explain"
    module: str = "ask"
    system_override: str = ""       # 非导师任务（如电脑助手出 JSON 计划）用
    use_tools: bool = True          # 纯生成任务别让它去查记录
    conversation_id: int | None = None   # 测验自动收题的去重键要用
    conversation_key: str = ""           # 快捷栏一轮对话的稳定 key
    material_id: int = 0                 # 从资料出题时，错题按资料归档


@dataclass
class _RunState:
    text: str = ""
    thinking: str = ""
    usage: dict = field(default_factory=dict)
    steps: int = 0
    stop_reason: str = ""


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
    """把「问/答」对变成 Anthropic 消息；图和它的转述只挂第一轮。"""
    turns = [(str(q), str(a)) for q, a in (history or []) if q]
    if not turns:
        return []
    if len(turns) > 4:                 # 保留第一轮（图挂在那儿）+ 最近三轮
        turns = [turns[0]] + turns[-3:]
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


def _tool_context(request: AgentRequest, cfg: AgentConfig) -> tools.ToolContext:
    return tools.ToolContext(
        data_root=pathlib.Path(cfg.data_root),
        attachment_name=request.attachment_name,
        attachment_text=request.attachment_text,
        conversation_id=request.conversation_id,
        conversation_key=request.conversation_key,
        mode=request.mode,
        material_id=request.material_id,
    )


def _execute_tool(call, ctx: tools.ToolContext) -> tuple[str, str]:
    content, preview = tools.execute(call.name, call.input, ctx)
    content = str(content or "").strip() or "（工具没有返回内容）"
    return f'<record source="{call.name}">\n{content}\n</record>', preview


def _default_provider():
    from learnsys.agent import provider_anthropic
    return provider_anthropic


def run(request: AgentRequest, *, provider=None, cfg: AgentConfig | None = None,
        abort: threading.Event | None = None,
        response_sink: list | None = None,
        max_steps: int = MAX_TOOL_STEPS) -> Iterator[AgentEvent]:
    """跑一轮 Agent，边跑边 yield 事件。失败只发 error，不抛给界面。"""
    cfg = cfg or load_config()
    if not cfg.ready:
        yield AgentEvent("error", text=(
            "还没配置模型。打开「设置」，填一个 Anthropic / OpenAI 兼容服务的地址和密钥；"
            "也可以先在 D:/学习系统/设置.json 里填 agent.base_url、agent.auth_token、agent.model。"))
        return
    if abort is not None and abort.is_set():
        yield AgentEvent("done", data={"text": "", "stop_reason": "aborted"})
        return

    provider = provider or _default_provider()
    profile = _read_profile(cfg)
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
        return

    system = (request.system_override.strip()
              or prompts.build_system(request.mode, has_image=bool(image_paths), profile=profile))
    tool_schemas = tools.schemas_for(request.mode, use_tools=request.use_tools)
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

    state = _RunState()
    ctx = _tool_context(request, cfg)
    try:
        for step in range(max(1, int(max_steps))):
            state.steps = step + 1
            result: ProviderResult | None = None
            for event in provider.stream_messages(
                    cfg, system, messages, tool_schemas,
                    abort=abort, response_sink=response_sink):
                if event.kind == "text":
                    yield AgentEvent("text", text=event.text)
                elif event.kind == "thinking":
                    yield AgentEvent("thinking", text=event.text)
                elif event.kind == "done":
                    result = event.result
            if result is None:
                raise AgentError("模型没有返回结果（连接可能被中断了）。")
            state.stop_reason = result.stop_reason

            if result.text:
                state.text = (state.text + ("\n\n" if state.text else "") + result.text).strip()
            if result.thinking:
                state.thinking += result.thinking
            if result.usage:
                state.usage.update(result.usage)
            if result.stop_reason == "aborted":
                yield AgentEvent("done", data={
                    "text": state.text, "thinking": state.thinking,
                    "stop_reason": "aborted", "steps": state.steps,
                })
                return

            if result.stop_reason == "tool_use" and result.tool_calls:
                assistant_content = result.content_blocks or (
                    [{"type": "text", "text": result.text}] if result.text else [])
                messages.append({"role": "assistant", "content": assistant_content})
                tool_results: list[dict] = []
                for call in result.tool_calls:
                    if abort is not None and abort.is_set():
                        yield AgentEvent("done", data={
                            "text": state.text, "thinking": state.thinking,
                            "stop_reason": "aborted", "steps": state.steps,
                        })
                        return
                    yield AgentEvent("tool_start", data={"name": call.name, "input": call.input})
                    content, preview = _execute_tool(call, ctx)
                    yield AgentEvent("tool_end", data={"name": call.name, "preview": preview})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": content,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue
            break

        if state.stop_reason == "tool_use":
            raise AgentError("工具调用次数太多，先停一下 —— 换个更具体的问题试试。")
        final_text = state.text.strip()
        if not final_text:
            raise AgentError("答案回来了但是空的，再问一次试试。")
        # 没配视觉模型时，不管模型自不自觉，都在最前面钉一句「没看到原图」。
        # 这比事后猜它有没有说更可靠 —— 用户不能把 OCR 推断当成真看了图。
        if image_paths and not used_vision and "OCR" not in final_text and "没看到原图" not in final_text:
            final_text = ("（本次没看到原图，以下回答按 OCR 文字推断；"
                          "箭头、版式、颜色请对照原图核对。）\n\n" + final_text)
        yield AgentEvent("done", data={
            "text": final_text,
            "thinking": state.thinking,
            "usage": state.usage,
            "steps": state.steps,
            "stop_reason": state.stop_reason or "end_turn",
        })
    except ProviderError as exc:
        yield AgentEvent("error", text=str(exc))
    except AgentError as exc:
        yield AgentEvent("error", text=str(exc))
    except Exception as exc:           # 兜底：后台异常不能把界面搞死
        yield AgentEvent("error", text=f"Agent 出错了：{exc}")
