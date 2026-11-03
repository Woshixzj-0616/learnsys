"""自动模型路由（影子优先）。

口径：
- **手动速度档优先**：用户选了 fast / deep，就照用户的；只有 balanced 才让自动路由提建议。
- **手动 routes 优先**：设置里给某个 mode 指了模型，就不再自动判断。
- **纯规则，不调用模型**：可解释、可测试、零额外成本；影子模式只记录建议，不改实际行为。
- 自动升级目标模型取 `agent.strong_model`；没填就退回主模型（只多开思考）。

判据只影响 `explain` / `guide`：其余模式按固定档位。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from learnsys.agent import debug_intent, intent
from learnsys.llm.config import AgentConfig

# 难度信号：命中两个以上才算“需要深入”。这些词不是绝对标准，只是可解释的粗筛。
HARD_WORDS = (
    "为什么", "原理", "推导", "证明", "复杂度", "对比", "区别", "设计",
    "重构", "排错", "报错", "源码", "并发", "死锁", "内存", "指针",
    "虚函数", "协议", "算法", "底层", "架构", "性能",
)

COMPLEX_MODES = {"explain", "guide"}


@dataclass(frozen=True)
class RouteDecision:
    tier: str                 # fast / standard / deep / manual
    model: str
    thinking: bool
    concise: bool
    reason: str
    recommended: dict | None = None   # 影子模式下的建议，供流水记录
    ops: dict | None = None           # 排错/配置意图（shadow 只记录，不改路由）

    def trace(self) -> dict:
        data = {"tier": self.tier, "model": self.model, "thinking": self.thinking,
                "reason": self.reason}
        if self.recommended:
            data["recommended"] = dict(self.recommended)
        if self.ops:
            data["ops"] = dict(self.ops)
        return data


def _base_speed(cfg: AgentConfig, mode: str) -> str:
    speed = (cfg.speed or "balanced").lower()
    if mode == "quick":
        speed = "fast"
    return speed if speed in ("fast", "balanced", "deep") else "balanced"


def _ops_trace(cfg: AgentConfig, ops: intent.OpsIntent) -> dict:
    """记录排错意图，供 `agent_runs.trace_json` 核对。"""
    return {
        "ops": True,
        "kind": ops.kind,
        "signals": list(ops.signals),
        "confidence": round(float(ops.confidence), 2),
        "needs_evidence": bool(ops.needs_evidence),
        "recommended": {"tier": "deep", "thinking": True, "concise": False,
                        "model": cfg.strong_model or cfg.model},
    }


def _auto_tier(cfg: AgentConfig, *, mode: str, message: str, context: str,
               attachment_text: str, history_len: int, has_image: bool,
               ops: intent.OpsIntent | None = None) -> dict:
    """返回自动路由的建议档位（不关心当前 speed）。"""
    if mode == "quick":
        return {"tier": "fast", "model": cfg.fast_model or cfg.model, "thinking": False,
                "concise": True, "reason": "速答模式"}
    if mode == "deep":
        return {"tier": "deep", "model": cfg.strong_model or cfg.model, "thinking": True,
                "concise": False, "reason": "显式深入模式"}
    if ops is not None and ops.ops:
        return {"tier": "deep", "model": cfg.strong_model or cfg.model, "thinking": True,
                "concise": False,
                "reason": "排错/配置：" + ("、".join(ops.signals[:3]) or ops.kind)}
    if mode not in COMPLEX_MODES:
        return {"tier": "standard", "model": cfg.model, "thinking": False,
                "concise": True, "reason": "固定档位"}

    # 代码调试优先于长度/关键词：实测不思考会瞎试、反复超时（2026-10-27 会话 45/46）。
    intent = debug_intent.detect(message)
    if intent["code_debug"]:
        return {"tier": "deep", "model": cfg.model, "thinking": True,
                "concise": False,
                "reason": "代码调试（{}）：先运行验证".format(
                    "、".join(intent["signals"]) or "粘贴代码")}

    hits = sum(1 for word in HARD_WORDS if word in (message or ""))
    score = 3 if hits >= 3 else (2 if hits == 2 else (1 if hits == 1 else 0))
    factors = [f"{hits} 个难度词"] if hits else []
    length = len(message or "")
    if length >= 300:
        score += 2
        factors.append(f"{length} 字长问题")
    elif length >= 120:
        score += 1
        factors.append(f"{length} 字")
    if len(context or "") + len(attachment_text or "") >= 1500:
        score += 1
        factors.append("上下文/附件较长")
    if history_len >= 6:
        score += 1
        factors.append("对话轮次多")
    if has_image:
        score += 1
        factors.append("带图")

    detail = "、".join(factors) or "没有明显难度信号"
    if score >= 3:
        return {"tier": "deep", "model": cfg.strong_model or cfg.model, "thinking": True,
                "concise": False, "reason": f"复杂度 {score}：{detail}"}
    return {"tier": "standard", "model": cfg.model, "thinking": False, "concise": True,
            "reason": f"复杂度 {score}：{detail}"}


def decide(cfg: AgentConfig, *, mode: str, message: str = "", context: str = "",
           attachment_text: str = "", history_len: int = 0,
           has_image: bool = False, ops: intent.OpsIntent | None = None) -> RouteDecision:
    """给出这一轮实际使用的档位；shadow 时保留原行为，只带出 recommended。

    ops 是独立的一道开关：off 忽略；shadow 只写 trace；on 在 balanced 档强制深入。
    手动速度档（fast / deep）和手动 routes 仍然优先。
    """
    speed = _base_speed(cfg, mode)
    routed = cfg.model_for(mode)
    ops_mode = str(getattr(cfg, "ops_mode", "shadow") or "shadow").strip().lower()
    ops_trace = (_ops_trace(cfg, ops)
                 if ops is not None and ops.ops and ops_mode != "off" else None)
    if routed:
        return RouteDecision(
            tier="manual", model=routed, thinking=speed == "deep",
            concise=speed != "deep", reason=f"手动路由：{mode} → {routed}",
            ops=ops_trace)
    if speed == "deep":
        # 手动深入档只用主模型；强模型只在自动路由生效时升级用。
        return RouteDecision(tier="deep", model=cfg.model,
                             thinking=True, concise=False, reason="速度档：深入",
                             ops=ops_trace)
    if speed == "fast":
        return RouteDecision(tier="fast", model=cfg.fast_model or cfg.model,
                             thinking=False, concise=True, reason="速度档：快",
                             ops=ops_trace)
    # 排错/配置题：只要没被手动档拦住，就按深入 + 思考走。
    if ops_mode == "on" and ops_trace is not None:
        return RouteDecision(
            tier="deep", model=cfg.strong_model or cfg.model,
            thinking=True, concise=False,
            reason="排错/配置：" + ("、".join(ops.signals[:3]) or ops.kind),
            ops=ops_trace)
    # 只有 balanced 才自动判断；auto_route=off 时保持原样。
    auto = (cfg.auto_route or "off").lower()
    if auto not in ("shadow", "on"):
        return RouteDecision(tier="standard", model=cfg.model, thinking=False,
                             concise=True, reason="速度档：平衡", ops=ops_trace)
    suggestion = _auto_tier(cfg, mode=mode, message=message, context=context,
                            attachment_text=attachment_text,
                            history_len=history_len, has_image=has_image, ops=ops)
    if auto == "shadow":
        return RouteDecision(tier="standard", model=cfg.model, thinking=False,
                             concise=True, reason="速度档：平衡（影子）",
                             recommended=suggestion, ops=ops_trace)
    return RouteDecision(tier=suggestion["tier"], model=suggestion["model"],
                         thinking=bool(suggestion["thinking"]),
                         concise=bool(suggestion["concise"]),
                         reason=str(suggestion["reason"]), ops=ops_trace)


def apply(cfg: AgentConfig, decision: RouteDecision) -> AgentConfig:
    """把决策落到配置上。manual / 原档位时值不变，dataclasses.replace 仍然安全。"""
    return dataclasses.replace(cfg, model=decision.model,
                               thinking=bool(decision.thinking))
