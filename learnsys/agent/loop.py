"""Agent 循环：看图 → 组装上下文 → 流式回答 → 需要时调工具 → 再回答。

界面只跟 `run()` 打交道；模型协议在 `provider_anthropic` 里，工具在 `tools` 里，
提示词在 `prompts` 里。三块都可以单独测。
"""
from __future__ import annotations

import dataclasses
import pathlib
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from learnsys.agent import memory, planning, prompts, selfcheck, tools, vision
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
    plan: list[dict] = field(default_factory=list)
    evidence: selfcheck.Evidence = field(default_factory=selfcheck.Evidence)
    denied_writes: list[str] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0


def _merge_usage(target: dict, update) -> None:
    """多轮模型调用的 token 要相加，不能后一轮覆盖前一轮。"""
    if not isinstance(update, dict):
        return
    for key, value in update.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] = target.get(key, 0) + value
        else:
            target.setdefault(key, value)


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
        db_path=pathlib.Path(cfg.data_root) / "learning.db",
        attachment_name=request.attachment_name,
        attachment_text=request.attachment_text,
        conversation_id=request.conversation_id,
        conversation_key=request.conversation_key,
        mode=request.mode,
        material_id=request.material_id,
    )


def _execute_tool(call, ctx: tools.ToolContext) -> tuple[str, str, bool, str]:
    """返回 (包好的记录, 界面摘要, 是否成功, 原始内容)；自检要拿未包裹的原文。"""
    raw, preview, ok = tools.execute(call.name, call.input, ctx)
    raw = str(raw or "").strip() or "（工具没有返回内容）"
    return f'<record source="{call.name}">\n{raw}\n</record>', preview, ok, raw


def _default_provider():
    from learnsys.agent import provider_anthropic
    return provider_anthropic


def _rewrite_answer(provider, cfg: AgentConfig, state: _RunState, answer: str,
                    issues: list[str], abort) -> str:
    """自检不通过：用快模型按证据重写一次（不再调工具）。失败返回空串。"""
    if abort is not None and abort.is_set():
        return ""
    rewrite_cfg = dataclasses.replace(cfg, thinking=False)
    user = selfcheck.build_rewrite_user(answer, issues, state.evidence.digest())
    messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
    parts: list[str] = []
    result: ProviderResult | None = None
    state.model_calls += 1
    for event in provider.stream_messages(
            rewrite_cfg, selfcheck.REWRITE_SYSTEM, messages, None,
            abort=abort, response_sink=None):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    if result is not None and result.usage:
        _merge_usage(state.usage, result.usage)
    text = (result.text if result is not None and result.text
            else "".join(parts)).strip()
    return text


def _speed_config(cfg: AgentConfig, mode: str) -> tuple[AgentConfig, bool]:
    """按「回答速度」档定模型和思考开关，返回 (配置, 是否用精简提示词)。

    - fast：轻量模型 + 不思考（实测约 7 秒，适合速答/横栏快问）
    - balanced：**同一个主模型** + 不思考（实测约 10–20 秒，质量口径不变，少掉冗长思考）
    - deep：主模型 + 思考（深入推导；最慢）
    模式 quick 永远走 fast —— 用户选「速答」就是要快。
    """
    speed = (cfg.speed or "balanced").lower()
    if mode == "quick":
        speed = "fast"
    if speed == "fast":
        return (dataclasses.replace(cfg, model=cfg.fast_model or cfg.model,
                                    thinking=False), True)
    if speed == "deep":
        return (dataclasses.replace(cfg, thinking=True), False)
    return (dataclasses.replace(cfg, thinking=False), True)


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
    if not cfg.ready:
        yield AgentEvent("error", text=(
            "还没配置模型。打开「设置」，填一个 Anthropic / OpenAI 兼容服务的地址和密钥；"
            "也可以先在 D:/学习系统/设置.json 里填 agent.base_url、agent.auth_token、agent.model。"))
        return
    if abort is not None and abort.is_set():
        yield AgentEvent("done", data={"text": "", "stop_reason": "aborted"})
        return

    provider = provider or _default_provider()
    cfg, concise = _speed_config(cfg, request.mode)
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
        return

    system = (request.system_override.strip()
              or prompts.build_system(request.mode, has_image=bool(image_paths),
                                      profile=profile, memories=memory_text,
                                      concise=concise))
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
            state.model_calls += 1
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
                _merge_usage(state.usage, result.usage)
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

                    # 计划不是普通工具：不查库，只登记步骤并让界面看到。
                    if call.name == "make_plan":
                        raw_steps = (call.input or {}).get("steps")
                        steps, truncated = planning.normalize_steps(raw_steps)
                        if steps:
                            state.plan = steps
                            yield AgentEvent("plan", data={"steps": steps,
                                                          "truncated": truncated})
                            content = ("计划已登记，按顺序执行；某步失败就如实说明或换路，"
                                       "不要当成成功。\n" + planning.summary_text(steps)
                                       + ("\n（超过 6 步的部分已截断。）" if truncated else ""))
                            preview, ok = f"列了 {len(steps)} 步计划", True
                        else:
                            content = "计划为空：请给出 2–6 步，每步一句话写清做什么。"
                            preview, ok = "计划为空", False
                        yield AgentEvent("tool_end", data={
                            "name": call.name, "preview": preview, "ok": ok})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": f'<record source="make_plan">\n{content}\n</record>',
                        })
                        continue

                    step_index = planning.match_step(state.plan, call.name)
                    goal = (state.plan[step_index]["title"]
                            if step_index is not None else "")
                    if planning.mark_step(state.plan, step_index, "doing"):
                        yield AgentEvent("plan_update", data={
                            "index": step_index, "status": "doing",
                            "steps": state.plan})
                    state.tool_calls += 1
                    yield AgentEvent("tool_start", data={
                        "name": call.name, "input": call.input,
                        "goal": goal, "step": step_index})

                    if call.name in tools.CONFIRM_TOOLS:
                        approved = False
                        if confirm is not None:
                            request_id = uuid.uuid4().hex[:12]
                            yield AgentEvent("confirm", data={
                                "request_id": request_id,
                                "tool": call.name,
                                "summary": tools.write_summary(call.name, call.input),
                                "goal": goal,
                            })
                            try:
                                approved = bool(confirm(request_id, call.name, call.input))
                            except Exception:
                                approved = False
                        if abort is not None and abort.is_set():
                            yield AgentEvent("done", data={
                                "text": state.text, "thinking": state.thinking,
                                "stop_reason": "aborted", "steps": state.steps,
                            })
                            return
                        if not approved:
                            label = tools.WRITE_LABELS.get(call.name, call.name)
                            state.denied_writes.append(
                                tools.write_summary(call.name, call.input))
                            raw = (f"用户没有确认这次写入（{label}），工具没有执行。"
                                   "不要当成已经写入；需要的话用一句话说明请在界面上确认。")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": call.id,
                                "content": f'<record source="{call.name}">\n{raw}\n</record>',
                            })
                            yield AgentEvent("tool_end", data={
                                "name": call.name, "preview": "用户拒绝了写入",
                                "ok": False, "denied": True, "goal": goal,
                                "step": step_index})
                            if planning.mark_step(state.plan, step_index, "failed"):
                                yield AgentEvent("plan_update", data={
                                    "index": step_index, "status": "failed",
                                    "steps": state.plan})
                            continue

                    tool_started = time.monotonic()
                    content, preview, ok, raw = _execute_tool(call, ctx)
                    tool_ms = int((time.monotonic() - tool_started) * 1000)
                    # 代码运行的输出即使失败（编译错误 / 超时）也是可引用的证据；
                    # 写入失败则不是，不能拿来当来源。
                    if ok or call.name == "run_code":
                        state.evidence.add(call.name, call.input, raw)
                    if planning.mark_step(state.plan, step_index,
                                          "done" if ok else "failed"):
                        yield AgentEvent("plan_update", data={
                            "index": step_index,
                            "status": "done" if ok else "failed",
                            "steps": state.plan})
                    end_data = {"name": call.name, "preview": preview, "ok": ok,
                                "goal": goal, "step": step_index, "ms": tool_ms}
                    if call.name == "run_code":
                        # 审计要看到真实输出与退出码，而不只是一句「运行成功」
                        end_data["output"] = raw[:12000]
                    yield AgentEvent("tool_end", data=end_data)
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

        # 真踩过的坑（2026-10-22，会话 14）：模型只吐了思考、正文一个字没有，
        # 用户等了 2 分钟收到「答案回来了但是空的」。思考是有价值的，不能一丢了之。
        # 这里自动用「不思考」模式重答一次：既避开 thinking 吃满输出上限，也更快。
        if (not final_text and state.thinking.strip()
                and (abort is None or not abort.is_set())):
            retry_cfg = dataclasses.replace(cfg, thinking=False)
            retry_result = None
            state.model_calls += 1
            yield AgentEvent("activity", text="模型只输出了思考，正在改用快答重试…")
            for event in provider.stream_messages(
                    retry_cfg, system, messages, None,
                    abort=abort, response_sink=response_sink):
                if event.kind == "text":
                    state.text += event.text
                    yield AgentEvent("text", text=event.text)
                elif event.kind == "done":
                    retry_result = event.result
            if retry_result is not None:
                state.stop_reason = retry_result.stop_reason or state.stop_reason
                if retry_result.text:
                    state.text = retry_result.text
                if retry_result.usage:
                    _merge_usage(state.usage, retry_result.usage)
            state.steps += 1
            final_text = state.text.strip()

        if not final_text:
            reason = {
                "max_tokens": "达到回答上限",
                "end_turn": "模型提前结束",
            }.get(state.stop_reason, state.stop_reason or "未知原因")
            hint = ("模型这次只输出了思考过程，没有写出正文"
                    f"（{reason}）。已经自动用快答重试过；仍为空，"
                    "可以把问题拆小一点，或在设置里调高「回答上限」。")
            raise AgentError(hint)
        # 没配视觉模型时，不管模型自不自觉，都在最前面钉一句「没看到原图」。
        # 这比事后猜它有没有说更可靠 —— 用户不能把 OCR 推断当成真看了图。
        if image_paths and not used_vision and "OCR" not in final_text and "没看到原图" not in final_text:
            final_text = ("（本次没看到原图，以下回答按 OCR 文字推断；"
                          "箭头、版式、颜色请对照原图核对。）\n\n" + final_text)

        # 回答写完了，把计划里还没动静的步骤收个尾：
        # 不需要工具的「汇总/讲解」步 = 已完成；声明了工具却没做的 = 跳过（不假装做过）。
        if state.plan and final_text:
            changed = False
            for step in state.plan:
                if step.get("status") == "pending":
                    step["status"] = "done" if not step.get("tool") else "skipped"
                    changed = True
            if changed:
                yield AgentEvent("plan_update", data={
                    "index": state.plan[-1]["index"],
                    "status": state.plan[-1]["status"],
                    "steps": state.plan})

        # 自检：只查「能被工具结果核对」的引用。速答模式跳过（用户就是要快）。
        issues: list[str] = []
        if (state.evidence.results and final_text and request.mode != "quick"
                and (abort is None or not abort.is_set())):
            issues = selfcheck.verify(final_text, state.evidence)
            yield AgentEvent("check", data={
                "ok": not issues, "issues": issues,
                "checked": len(state.evidence.results)})
            if issues:
                yield AgentEvent("activity",
                                 text=f"自检发现 {len(issues)} 处引用对不上，正在重写…")
                rewritten = _rewrite_answer(provider, cfg, state, final_text,
                                            issues, abort)
                if rewritten:
                    final_text = rewritten
                    state.text = rewritten
                    yield AgentEvent("rewrite", data={
                        "text": rewritten, "reason": "自检后发现引用问题，已重写"})
                    issues = selfcheck.verify(final_text, state.evidence)
                    yield AgentEvent("check", data={
                        "ok": not issues, "issues": issues,
                        "checked": len(state.evidence.results), "rewritten": True})
                if issues:
                    note = selfcheck.note_for(issues)
                    final_text += note
                    state.text = final_text

        # 写操作 / 运行代码被拒时，模型有时仍会说「已记住 / 已运行」。这是不可接受的：
        # 在答案末尾钉一条系统提示，保证用户不会以为真的发生了（自检重写也抹不掉它）。
        if state.denied_writes and final_text:
            final_text += ("\n\n> **没有执行**：下面这些操作需要你确认，但这次没有执行：\n"
                           + "\n".join(f"> - {item}"
                                       for item in state.denied_writes))
            state.text = final_text

        yield AgentEvent("done", data={
            "text": final_text,
            "thinking": state.thinking,
            "usage": state.usage,
            "steps": state.steps,
            "model_calls": state.model_calls,
            "tool_calls": state.tool_calls,
            "stop_reason": state.stop_reason or "end_turn",
            "truncated": state.stop_reason == "max_tokens",
        })
    except ProviderError as exc:
        yield AgentEvent("error", text=str(exc))
    except AgentError as exc:
        yield AgentEvent("error", text=str(exc))
    except Exception as exc:           # 兜底：后台异常不能把界面搞死
        yield AgentEvent("error", text=f"Agent 出错了：{exc}")
