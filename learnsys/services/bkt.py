"""BKT（Bayesian Knowledge Tracing）纯函数。

FSRS 管「何时复习」，BKT 管「懂没懂」。这里只管概率更新与等级，
不碰数据库、不碰 FastAPI；样本取数统一走 `store.ready_attempts()`。
"""
from __future__ import annotations

PARAMS = {"p_l0": 0.1, "p_t": 0.15, "p_s": 0.1, "p_g": 0.25}
MIN_SAMPLES = 5
WEAK_BELOW = 0.4
MASTERED_AT = 0.7
EPS = 0.001
_EXCLUDED = ["其他"]


def _params(params: dict | None) -> dict:
    return params or PARAMS


def _clamp(value: float) -> float:
    return max(EPS, min(1.0 - EPS, float(value)))


def observe(p: float, correct: bool, params: dict | None = None) -> float:
    """一次作答后的掌握概率：先贝叶斯后验，再学习转移。

    `correct` 必须是真正的布尔；`None` 表示没判出来，不能当答错。
    """
    if not isinstance(correct, bool):
        raise ValueError("correct 必须是 True/False；没判出来请先不要传")
    cfg = _params(params)
    p = max(0.0, min(1.0, float(p)))
    slip = float(cfg["p_s"])
    guess = float(cfg["p_g"])
    learn = float(cfg["p_t"])
    if correct:
        numerator = p * (1.0 - slip)
        denominator = numerator + (1.0 - p) * guess
    else:
        numerator = p * slip
        denominator = numerator + (1.0 - p) * (1.0 - guess)
    posterior = numerator / max(denominator, 1e-12)
    return _clamp(posterior + (1.0 - posterior) * learn)


def mastery(observations, params: dict | None = None) -> float:
    """按顺序 fold 一组对错；空列表返回先验 L0。"""
    cfg = _params(params)
    p = float(cfg["p_l0"])
    for correct in observations or []:
        p = observe(p, correct, cfg)
    return p


def level(mastery_value: float | None, attempts: int, *, modeled: bool = True,
          min_samples: int = MIN_SAMPLES) -> str:
    """产品等级；样本不足时不给等级，避免把噪声当结论。"""
    if not modeled:
        return "不建模"
    if int(attempts or 0) <= 0:
        return "未开始"
    if mastery_value is None or int(attempts) < int(min_samples):
        return "样本不足"
    value = float(mastery_value)
    if value < WEAK_BELOW:
        return "薄弱"
    if value < MASTERED_AT:
        return "在学"
    return "掌握"


def params_meta() -> dict:
    """给 API 暴露的静态说明，前端不用再硬编码 5 / 0.4 / 0.7。"""
    return {
        "params": dict(PARAMS),
        "min_samples": MIN_SAMPLES,
        "weak_below": WEAK_BELOW,
        "mastered_at": MASTERED_AT,
        "excluded": list(_EXCLUDED),
    }
