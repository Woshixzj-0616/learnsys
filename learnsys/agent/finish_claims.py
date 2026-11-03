"""收尾 · 取证审核：没有证据的绝对断言打回重写一次。

单独成模块是因为 `turn.py` 已贴近 500 行门禁；这里只做「审核 → 重写 → 未核实项」，
规则仍只在 `claims.py`，提示词仍只在 `prompt_ops.py`，不另存一份口径。
"""
from __future__ import annotations

from collections.abc import Generator

from learnsys.agent import claims, prompt_ops
from learnsys.agent.events import AgentEvent


def _texts(issues) -> list[str]:
    return [claims.issue_text(issue) for issue in issues]


def apply(turn, final_text: str, abort) -> Generator[AgentEvent, None, str]:
    """返回修正后的正文；没有启用/没有问题时原样返回。

    门槛也在这里判断：turn.py 只留一行调用，避免贴着 500 行门禁继续长。
    """
    cfg = turn.cfg_holder[0]
    if (not turn.ops or not getattr(cfg, "claim_audit", True) or not final_text
            or (abort is not None and abort.is_set())):
        return final_text
    state = turn.state
    issues = claims.audit(final_text, state.evidence, turn.request.message, ops=True)
    yield AgentEvent("check", data={"ok": not issues, "kind": "claims",
                                    "issues": _texts(issues)})
    if not issues:
        return final_text

    # 延迟导入：turn.py 在模块顶部 import 本文件，顶层互相 import 会成环。
    from learnsys.agent.turn import _rewrite_answer

    yield AgentEvent("activity",
                     text=f"取证审核发现 {len(issues)} 处没有证据的断言，正在修正…")
    digest = state.evidence.digest()
    urls = sorted(state.evidence.urls())
    if urls:
        # 摘要只有 7KB，链接可能在截断之外；单独列出来，避免把真链接当假的删掉。
        digest += ("\n\n【证据里出现过的链接（可以引用）】\n"
                   + "\n".join(urls[:20]))
    rewritten = _rewrite_answer(
        turn.provider, cfg, state, final_text, _texts(issues), abort,
        source=str(getattr(turn.request, "mode", "") or ""),
        system=prompt_ops.REWRITE_SYSTEM,
        user_text=prompt_ops.build_rewrite_user(final_text, issues, digest))
    if rewritten:
        final_text = rewritten
        state.text = rewritten
        yield AgentEvent("rewrite", data={
            "text": rewritten, "reason": "取证审核后发现没有证据的断言，已重写"})
        issues = claims.audit(final_text, state.evidence,
                              turn.request.message, ops=True)
        yield AgentEvent("check", data={"ok": not issues, "kind": "claims",
                                        "issues": _texts(issues), "rewritten": True})
    if issues:
        final_text += claims.note_for(issues)
        state.text = final_text
    return final_text
