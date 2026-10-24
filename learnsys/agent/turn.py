"""一轮 Agent 的步骤实现：流式调用、工具轮次、思考重试、收尾。

`loop.run()` 只负责编排；这里按「一次模型调用 / 一次工具调用 / 一段收尾」
拆开，事件顺序和状态仍来自同一个 `_RunState` 与 `messages`，不另存一份。
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field

from learnsys.agent import planning, selfcheck, tools
from learnsys.llm.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.agent.fallback import stream_with_fallback
from learnsys.llm.provider_anthropic import ProviderResult


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


@dataclass
class _Turn:
    """一轮里会跨步骤共享的东西；`cfg_holder` 在降级后会换成轻量模型。"""
    request: AgentRequest
    provider: object
    cfg_holder: list
    system: str
    tool_schemas: list | None
    messages: list
    state: _RunState
    ctx: tools.ToolContext
    image_paths: list[str]
    used_vision: bool


def _merge_usage(target: dict, update) -> None:
    """多轮模型调用的 token 要相加，不能后一轮覆盖前一轮。"""
    if not isinstance(update, dict):
        return
    for key, value in update.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] = target.get(key, 0) + value
        else:
            target.setdefault(key, value)


def _aborted(state: _RunState) -> AgentEvent:
    return AgentEvent("done", data={
        "text": state.text, "thinking": state.thinking,
        "stop_reason": "aborted", "steps": state.steps,
    })


def _execute_tool(call, ctx: tools.ToolContext) -> tuple[str, str, bool, str]:
    """返回 (包好的记录, 界面摘要, 是否成功, 原始内容)；自检要拿未包裹的原文。"""
    raw, preview, ok = tools.execute(call.name, call.input, ctx)
    raw = str(raw or "").strip() or "（工具没有返回内容）"
    return f'<record source="{call.name}">\n{raw}\n</record>', preview, ok, raw


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


def _stream_once(provider, cfg_holder: list, system: str, messages: list,
                 tool_schemas, abort, response_sink,
                 state: _RunState) -> Generator[AgentEvent, None, ProviderResult | None]:
    """一次模型流式调用：增量事件原样透传，返回最终结果并合并 usage。"""
    result: ProviderResult | None = None
    for event in stream_with_fallback(
            provider, cfg_holder, system, messages, tool_schemas,
            abort, response_sink):
        if event.kind == "text":
            yield AgentEvent("text", text=event.text)
        elif event.kind == "thinking":
            yield AgentEvent("thinking", text=event.text)
        elif event.kind == "activity":
            # 降级提示由 stream_with_fallback 发出，这里原样透传。
            yield AgentEvent("activity", text=event.text)
        elif event.kind == "done":
            result = event.result
    if result is not None and result.usage:
        _merge_usage(state.usage, result.usage)
    return result


def _handle_tool_call(turn: _Turn, call, tool_results: list[dict], *,
                      confirm, abort) -> Generator[AgentEvent, None, bool]:
    """处理一次工具调用；返回 False 表示本轮已被中止。"""
    state = turn.state
    if abort is not None and abort.is_set():
        yield _aborted(state)
        return False

    # 计划不是普通工具：不查库，只登记步骤并让界面看到。
    if call.name == "make_plan":
        raw_steps = (call.input or {}).get("steps")
        steps, truncated = planning.normalize_steps(raw_steps)
        if steps:
            state.plan = steps
            yield AgentEvent("plan", data={"steps": steps, "truncated": truncated})
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
        return True

    step_index = planning.match_step(state.plan, call.name)
    goal = (state.plan[step_index]["title"] if step_index is not None else "")
    if planning.mark_step(state.plan, step_index, "doing"):
        yield AgentEvent("plan_update", data={
            "index": step_index, "status": "doing", "steps": state.plan})
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
            yield _aborted(state)
            return False
        if not approved:
            label = tools.WRITE_LABELS.get(call.name, call.name)
            state.denied_writes.append(tools.write_summary(call.name, call.input))
            raw = (f"用户没有确认这次操作（{label}），工具没有执行。"
                   "不要当成已经完成；需要的话用一句话说明请在界面上确认。")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": f'<record source="{call.name}">\n{raw}\n</record>',
            })
            yield AgentEvent("tool_end", data={
                "name": call.name, "preview": "用户拒绝了操作",
                "ok": False, "denied": True, "goal": goal, "step": step_index})
            if planning.mark_step(state.plan, step_index, "failed"):
                yield AgentEvent("plan_update", data={
                    "index": step_index, "status": "failed", "steps": state.plan})
            return True

    tool_started = time.monotonic()
    content, preview, ok, raw = _execute_tool(call, turn.ctx)
    tool_ms = int((time.monotonic() - tool_started) * 1000)
    # 代码运行的输出即使失败（编译错误 / 超时）也是可引用的证据；
    # 写入失败则不是，不能拿来当来源。
    if ok or call.name == "run_code":
        state.evidence.add(call.name, call.input, raw)
    if planning.mark_step(state.plan, step_index, "done" if ok else "failed"):
        yield AgentEvent("plan_update", data={
            "index": step_index, "status": "done" if ok else "failed",
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
    return True


def _run_tool_loop(turn: _Turn, *, abort, response_sink, max_steps,
                   confirm) -> Generator[AgentEvent, None, bool]:
    """模型 ↔ 工具轮次主循环；返回 False 表示本轮已被中止。"""
    state = turn.state
    for step in range(max(1, int(max_steps))):
        state.steps = step + 1
        state.model_calls += 1
        result = yield from _stream_once(
            turn.provider, turn.cfg_holder, turn.system, turn.messages,
            turn.tool_schemas, abort, response_sink, state)
        if result is None:
            raise AgentError("模型没有返回结果（连接可能被中断了）。")
        state.stop_reason = result.stop_reason

        if result.text:
            state.text = (state.text + ("\n\n" if state.text else "")
                          + result.text).strip()
        if result.thinking:
            state.thinking += result.thinking
        if result.stop_reason == "aborted":
            yield _aborted(state)
            return False

        if result.stop_reason == "tool_use" and result.tool_calls:
            assistant_content = result.content_blocks or (
                [{"type": "text", "text": result.text}] if result.text else [])
            turn.messages.append({"role": "assistant", "content": assistant_content})
            tool_results: list[dict] = []
            for call in result.tool_calls:
                if not (yield from _handle_tool_call(
                        turn, call, tool_results,
                        confirm=confirm, abort=abort)):
                    return False
            turn.messages.append({"role": "user", "content": tool_results})
            continue
        break

    if state.stop_reason == "tool_use":
        raise AgentError("工具调用次数太多，先停一下 —— 换个更具体的问题试试。")
    return True


def _retry_thinking_only(turn: _Turn, *, abort,
                         response_sink) -> Generator[AgentEvent, None, None]:
    """只吐思考、正文为空时，用「不思考」模式重答一次。

    真踩过的坑（2026-10-22，会话 14）：用户等了 2 分钟收到「答案回来了但是空的」。
    思考是有价值的，不能一丢了之；不思考既避开 thinking 吃满输出上限，也更快。
    """
    state = turn.state
    if not (not state.text.strip() and state.thinking.strip()
            and (abort is None or not abort.is_set())):
        return
    retry_cfg = dataclasses.replace(turn.cfg_holder[0], thinking=False)
    retry_result: ProviderResult | None = None
    state.model_calls += 1
    yield AgentEvent("activity", text="模型只输出了思考，正在改用快答重试…")
    for event in turn.provider.stream_messages(
            retry_cfg, turn.system, turn.messages, None,
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


def _finish(turn: _Turn, *, abort) -> Generator[AgentEvent, None, None]:
    """答案收尾：空答案提示、OCR 横幅、计划收尾、自检重写、拒绝写提示、done。"""
    state = turn.state
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
    if (turn.image_paths and not turn.used_vision
            and "OCR" not in final_text and "没看到原图" not in final_text):
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
    if (state.evidence.results and final_text and turn.request.mode != "quick"
            and (abort is None or not abort.is_set())):
        issues = selfcheck.verify(final_text, state.evidence)
        yield AgentEvent("check", data={
            "ok": not issues, "issues": issues,
            "checked": len(state.evidence.results)})
        if issues:
            yield AgentEvent("activity",
                             text=f"自检发现 {len(issues)} 处引用对不上，正在重写…")
            rewritten = _rewrite_answer(turn.provider, turn.cfg_holder[0], state,
                                        final_text, issues, abort)
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
                       + "\n".join(f"> - {item}" for item in state.denied_writes))
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
