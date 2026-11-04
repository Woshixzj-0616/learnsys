"""一轮 Agent 的步骤实现：流式调用、工具轮次、思考重试、收尾。

`loop.run()` 只负责编排；这里按「一次模型调用 / 一次工具调用 / 一段收尾」
拆开，事件顺序和状态仍来自同一个 `_RunState` 与 `messages`，不另存一份。
"""
from __future__ import annotations

import dataclasses
import json
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field

from learnsys import config
from learnsys.agent import finish_turn, planning, selfcheck, tools
from learnsys.agent import usage as agent_usage
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
    personal_state: str = ""         # 路由层生成的三域状态（≤600 字），agent 只收字符串
    history_summary: str = ""        # 更早对话的压缩摘要（会话摘要功能写入）
    attachment_name: str = ""
    attachment_text: str = ""
    mode: str = "explain"
    module: str = "ask"
    surface: str = "ask"            # ask / cet6 / video / quickbar —— 决定工具裁剪
    system_override: str = ""       # 非导师任务（如电脑助手出 JSON 计划）用
    use_tools: bool = True          # 纯生成任务别让它去查记录
    conversation_id: int | None = None   # 测验自动收题的去重键要用
    conversation_key: str = ""           # 快捷栏一轮对话的稳定 key
    material_id: int = 0                 # 从资料出题时，错题按资料归档
    auto_run_code: bool = False          # 用户明确要求跑 / 代码调试：run_code 不再弹确认


@dataclass
class _RunState:
    text: str = ""
    thinking: str = ""
    usage: dict = field(default_factory=dict)
    usage_by_model: dict = field(default_factory=dict)   # 模型 → usage（账本口径）
    cost: float = 0.0
    currency: str = ""
    steps: int = 0
    stop_reason: str = ""
    plan: list[dict] = field(default_factory=list)
    evidence: selfcheck.Evidence = field(default_factory=selfcheck.Evidence)
    denied_writes: list[str] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    tools_used: set[str] = field(default_factory=set)       # 本轮调用过的工具名
    tools_ok: set[str] = field(default_factory=set)         # 至少成功过一次的工具名
    tool_seen: set[tuple] = field(default_factory=set)      # (工具名, 参数) 去重
    tool_attempts: dict[str, int] = field(default_factory=dict)
    gate_rounds: int = 0                                    # 取证补轮次数（最多 1）
    memory: dict = field(default_factory=dict)              # 本轮注入的记忆审计


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
    code_debug: bool = False          # 本轮是代码调试：收尾要检查有没有真的运行
    ops: bool = False                 # 本轮按排错处理（ops_mode=on）：收尾做取证审核


def _merge_usage(target: dict, update) -> None:
    """多轮模型调用的 token 要相加，不能后一轮覆盖前一轮。"""
    if not isinstance(update, dict):
        return
    for key, value in update.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] = target.get(key, 0) + value
        else:
            target.setdefault(key, value)


def _record_usage(state: _RunState, cfg, model: str, usage,
                  source: str = "") -> None:
    """一次成功的模型调用：合并用量 + 按模型记进账本。

    账本写失败只记日志，不让一轮对话因此失败——但每日上限会因此少算。
    """
    if not isinstance(usage, dict) or not usage:
        return
    model = str(model or "")
    _merge_usage(state.usage, usage)
    _merge_usage(state.usage_by_model.setdefault(model, {}), usage)
    amount, currency = agent_usage.record(
        getattr(cfg, "data_root", config.DATA_ROOT),
        source=source, model=model, usage=usage, cfg=cfg)
    state.cost = round(state.cost + amount, 8)
    state.currency = currency or state.currency


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
                    issues: list[str], abort, source: str = "rewrite",
                    system: str | None = None, user_text: str | None = None) -> str:
    """自检不通过：用快模型按证据重写一次（不再调工具）。失败返回空串。"""
    if abort is not None and abort.is_set():
        return ""
    rewrite_cfg = dataclasses.replace(cfg, thinking=False)
    user = user_text or selfcheck.build_rewrite_user(answer, issues, state.evidence.digest())
    messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
    parts: list[str] = []
    result: ProviderResult | None = None
    state.model_calls += 1
    for event in provider.stream_messages(
            rewrite_cfg, system or selfcheck.REWRITE_SYSTEM, messages, None,
            abort=abort, response_sink=None):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    if result is not None and result.usage:
        _record_usage(state, rewrite_cfg, rewrite_cfg.model, result.usage, source)
    text = (result.text if result is not None and result.text
            else "".join(parts)).strip()
    return text


def _stream_once(provider, cfg_holder: list, system: str, messages: list,
                 tool_schemas, abort, response_sink,
                 state: _RunState, source: str = "") -> Generator[AgentEvent, None, ProviderResult | None]:
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
            # 降级 / 续写提示由 stream_with_fallback 发出，这里原样透传（含 data.retry）。
            yield AgentEvent("activity", text=event.text, data=dict(event.data or {}))
        elif event.kind == "done":
            result = event.result
    if result is not None and result.usage:
        _record_usage(state, cfg_holder[0], cfg_holder[0].model, result.usage, source)
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

    # run_code 防抖（2026-10-27 实测：不思考时会拿错 stdin 连跑 8 次，每次超时 10 秒）。
    # 同一段代码 + 同一份 stdin 不重复跑；一轮最多 3 次。
    if call.name == "run_code":
        signature = ("run_code", json.dumps(call.input or {}, sort_keys=True,
                                            ensure_ascii=False, default=str))
        attempts = state.tool_attempts.get("run_code", 0)
        reason = ""
        if signature in state.tool_seen:
            reason = ("这次运行和上一轮完全相同，结果不会变；不要重复调用。"
                      "换一组输入，或根据已有输出下结论。")
        elif attempts >= 3:
            reason = ("本轮已经运行了 3 次代码；先根据已有输出下结论，不要继续运行。"
                      "如果还没定位，明说需要哪一组失败样例。")
        if reason:
            state.tool_calls += 1
            yield AgentEvent("tool_start", data={
                "name": call.name, "input": call.input,
                "label": tools.label_for(call.name)})
            yield AgentEvent("tool_end", data={
                "name": call.name, "preview": "重复/超限，已跳过", "ok": False})
            tool_results.append({
                "type": "tool_result", "tool_use_id": call.id,
                "content": f'<record source="run_code">\n{reason}\n</record>',
            })
            return True
        state.tool_seen.add(signature)
        state.tool_attempts["run_code"] = attempts + 1

    step_index = planning.match_step(state.plan, call.name)
    goal = (state.plan[step_index]["title"] if step_index is not None else "")
    if planning.mark_step(state.plan, step_index, "doing"):
        yield AgentEvent("plan_update", data={
            "index": step_index, "status": "doing", "steps": state.plan})
    state.tool_calls += 1
    yield AgentEvent("tool_start", data={
        "name": call.name, "input": call.input,
        "label": tools.label_for(call.name),
        "goal": goal, "step": step_index})

    if call.name in tools.CONFIRM_TOOLS:
        approved = False
        if call.name == "run_code" and getattr(turn.request, "auto_run_code", False):
            # 用户明确要求跑 / 代码调试：沙箱内自动执行，不再打断。
            approved = True
        elif confirm is not None:
            request_id = uuid.uuid4().hex[:12]
            yield AgentEvent("confirm", data={
                "request_id": request_id,
                "tool": call.name,
                "label": tools.label_for(call.name),
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
    state.tools_used.add(call.name)
    content, preview, ok, raw = _execute_tool(call, turn.ctx)
    if ok:
        state.tools_ok.add(call.name)
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
            turn.tool_schemas, abort, response_sink, state,
            source=str(getattr(turn.request, "mode", "") or ""))
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
    """答案收尾入口；具体步骤在 `finish_turn.py`（turn.py 贴着 500 行红线）。"""
    yield from finish_turn.apply(turn, abort=abort)
