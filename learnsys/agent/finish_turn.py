"""答案收尾：空答案提示、OCR 横幅、计划收尾、自检重写、取证审核、拒绝写提示、done。

从 `turn.py` 整体抽出（P31.2 起），给取证门控腾出 500 行红线内的空间。
逻辑和事件顺序与原 `_finish` 保持一致，不另存一份口径。
"""
from __future__ import annotations

from collections.abc import Generator

from learnsys.agent import finish_claims, selfcheck
from learnsys.agent.events import AgentEvent


def apply(turn, *, abort) -> Generator[AgentEvent, None, None]:
    # 延迟导入：turn.py 顶部 import 本模块，顶层互相 import 会成环。
    from learnsys.agent.turn import AgentError, _rewrite_answer

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
                                        final_text, issues, abort,
                                        source=str(getattr(turn.request, "mode", "") or ""))
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
                final_text += selfcheck.note_for(issues)
                state.text = final_text

    # 排错题：没有证据的绝对断言打回重写一次；门槛在 finish_claims 里判断。
    final_text = yield from finish_claims.apply(turn, final_text, abort)

    # 写操作 / 运行代码被拒时，模型有时仍会说「已记住 / 已运行」。这是不可接受的：
    # 在答案末尾钉一条系统提示，保证用户不会以为真的发生了（自检重写也抹不掉它）。
    if state.denied_writes and final_text:
        final_text += ("\n\n> **没有执行**：下面这些操作需要你确认，但这次没有执行：\n"
                       + "\n".join(f"> - {item}" for item in state.denied_writes))
        state.text = final_text

    # 代码调试题：没跑通就在最前面钉一句，不让用户把「读代码猜的」当成已验证结论。
    code_unverified = False
    if turn.code_debug and final_text and "run_code" not in state.tools_ok:
        if "run_code" in state.tools_used:
            note = ("（运行未成功：本轮代码没有跑通，以下结论没有运行输出支撑，"
                    "请以实际测试结果为准。）")
        else:
            note = ("（未运行验证：本轮没有实际编译 / 运行代码，以下只是静态分析，"
                    "结论可能有误。）")
        final_text = note + "\n\n" + final_text
        state.text = final_text
        code_unverified = True

    # 代码调试结束主动提议一次收进复习；只提议，不自动写 —— 是否值得收由用户确认。
    if turn.code_debug and final_text and "收进复习" not in final_text:
        final_text += ("\n\n> 想把这道题收进复习吗？回复「收进复习」，"
                       "我会先弹确认卡再保存。")
        state.text = final_text

    yield AgentEvent("done", data={
        "text": final_text,
        "thinking": state.thinking,
        "usage": state.usage,
        "usage_by_model": {name: dict(value)
                           for name, value in state.usage_by_model.items()},
        "cost": state.cost,
        "currency": state.currency,
        "steps": state.steps,
        "model_calls": state.model_calls,
        "tool_calls": state.tool_calls,
        "stop_reason": state.stop_reason or "end_turn",
        "truncated": state.stop_reason == "max_tokens",
        "code_unverified": code_unverified,
        "memory": dict(state.memory or {}),
        "prompt": dict(state.prompt or {}),
        "tool_tokens": state.tool_tokens,
    })
