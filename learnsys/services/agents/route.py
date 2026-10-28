"""外部 agent 的影子路由建议（P26.3）。

口径与 `learnsys/agent/router.py` 的影子模式一致：
- **纯规则、不调模型**，可解释、可测试、零额外成本；
- 只给建议，**不改变实际执行的 agent**；
- `done` 只表示任务正常结束，不是正确性 —— 文案统一叫「完成率」。
"""
from __future__ import annotations

from statistics import median

AGENT_ORDER = ("claude", "codex")
DEFAULT_NAMES = {"claude": "Claude Code", "codex": "Codex CLI"}
MIN_SAMPLES = 3
RATE_GAP = 0.2
SPEED_RATIO = 0.7
COST_RATIO = 0.7


def _name(agent: str, names: dict[str, str] | None) -> str:
    return (names or DEFAULT_NAMES).get(agent, agent)


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def stats(rows: list[dict]) -> dict:
    """完成率 = done/(done+failed)；cancelled 视为用户主动取消，不参与。"""
    done = [row for row in rows if str(row.get("status")) == "done"]
    failed = [row for row in rows if str(row.get("status")) == "failed"]
    cancelled = [row for row in rows if str(row.get("status")) == "cancelled"]
    total = len(done) + len(failed)
    durations = [float(row.get("duration_ms") or 0) for row in done
                 if float(row.get("duration_ms") or 0) > 0]
    costs = [float(row.get("cost_usd") or 0) for row in done
             if float(row.get("cost_usd") or 0) > 0]
    return {
        "n": total,
        "done": len(done),
        "failed": len(failed),
        "cancelled": len(cancelled),
        "rate": round(len(done) / total, 3) if total else 0.0,
        "median_ms": int(_median(durations)) if durations else 0,
        "median_cost": round(_median(costs), 6) if costs else None,
    }


def _other(agent: str) -> str:
    for item in AGENT_ORDER:
        if item != agent:
            return item
    return agent


def _seconds(ms: int) -> str:
    return f"{int(ms) / 1000:.0f} 秒"


def _sample_text(agent: str, data: dict, names: dict[str, str] | None) -> str:
    if not data["n"]:
        return f"{_name(agent, names)} 没有同模式历史"
    text = f"{_name(agent, names)} 完成 {data['done']}/{data['n']}"
    if data["median_ms"]:
        text += f"、中位 {_seconds(data['median_ms'])}"
    return text


def _result(*, chosen: str, recommended: str, mode: str, reason: str,
            samples: dict, fallback: str = "") -> dict:
    return {
        "v": 1, "recommended": recommended, "chosen": chosen, "mode": mode,
        "reason": reason, "samples": samples, "fallback": fallback,
    }


def recommend(*, mode: str, chosen: str, available: dict[str, bool],
              history: dict[str, list[dict]],
              names: dict[str, str] | None = None) -> dict:
    """返回影子建议。`history` 是 agent -> 最近终态任务列表。"""
    mode = "write" if str(mode or "read") == "write" else "read"
    chosen = str(chosen or "")
    other = _other(chosen)
    samples = {agent: stats(history.get(agent) or [])
               for agent in (chosen, other)}

    if not available.get(other, False):
        return _result(
            chosen=chosen, recommended=chosen, mode=mode,
            reason=f"{_name(other, names)} 现在不可用，沿用你的选择 "
                   f"{_name(chosen, names)}",
            samples=samples, fallback="other_unavailable")

    if mode == "write":
        if not available.get("claude", False):
            return _result(
                chosen=chosen, recommended="codex", mode=mode,
                reason="可写任务：Claude Code 不可用，只能用 Codex 的目录内授权",
                samples=samples, fallback="write_claude_unavailable")
        reason = ("可写任务：Claude Code 每次改文件 / 跑命令都逐条等你确认并留审计；"
                  "Codex 是整任务授权")
        return _result(chosen=chosen, recommended="claude", mode=mode,
                       reason=reason, samples=samples,
                       fallback="write_prefers_claude")

    mine, theirs = samples[chosen], samples[other]
    if mine["n"] < MIN_SAMPLES or theirs["n"] < MIN_SAMPLES:
        reason = (f"同模式历史样本不足（{_sample_text(chosen, mine, names)}；"
                  f"{_sample_text(other, theirs, names)}），沿用你的选择 "
                  f"{_name(chosen, names)}")
        return _result(chosen=chosen, recommended=chosen, mode=mode,
                       reason=reason, samples=samples,
                       fallback="insufficient_samples")

    if theirs["rate"] >= mine["rate"] + RATE_GAP:
        reason = (f"最近 {mine['n'] + theirs['n']} 条只读任务："
                  f"{_sample_text(other, theirs, names)}，"
                  f"{_sample_text(chosen, mine, names)}；"
                  f"完成率差距 ≥ {int(RATE_GAP * 100)} 个百分点")
        return _result(chosen=chosen, recommended=other, mode=mode,
                       reason=reason, samples=samples)

    if (abs(theirs["rate"] - mine["rate"]) < RATE_GAP
            and theirs["rate"] >= 0.8 and mine["rate"] >= 0.8
            and theirs["median_ms"] and mine["median_ms"]
            and theirs["median_ms"] <= mine["median_ms"] * SPEED_RATIO):
        reason = (f"完成率接近（{_name(chosen, names)} {mine['rate']:.0%}，"
                  f"{_name(other, names)} {theirs['rate']:.0%}），"
                  f"但 {_name(other, names)} 中位耗时 {_seconds(theirs['median_ms'])}，"
                  f"比 {_name(chosen, names)} 的 {_seconds(mine['median_ms'])} 快 30% 以上")
        return _result(chosen=chosen, recommended=other, mode=mode,
                       reason=reason, samples=samples)

    if (abs(theirs["rate"] - mine["rate"]) <= 0.05
            and theirs["median_cost"] and mine["median_cost"]
            and theirs["median_cost"] <= mine["median_cost"] * COST_RATIO):
        reason = (f"完成率接近（{mine['rate']:.0%} / {theirs['rate']:.0%}），"
                  f"{_name(other, names)} 中位单次费用 ${theirs['median_cost']:.4f}，"
                  f"低于 {_name(chosen, names)} 的 ${mine['median_cost']:.4f}")
        return _result(chosen=chosen, recommended=other, mode=mode,
                       reason=reason, samples=samples)

    if theirs["median_cost"] is None or mine["median_cost"] is None:
        cost_note = "；费用无可比数据（Codex 不自报费用）"
    else:
        cost_note = ""
    reason = (f"完成率与耗时没有明显差距（{_sample_text(chosen, mine, names)}；"
              f"{_sample_text(other, theirs, names)}），沿用你的选择 "
              f"{_name(chosen, names)}{cost_note}")
    return _result(chosen=chosen, recommended=chosen, mode=mode,
                   reason=reason, samples=samples)
