"""FSRS-5 调度器（纯函数，不碰数据库）。

评分：1 忘了 / 2 模糊 / 3 记得 / 4 简单。
目标记忆率 90%：此时「下次间隔 ≈ 稳定度（天）」。
"""
from __future__ import annotations

import datetime as dt
import math

# FSRS-5 默认权重（19 个）
DEFAULT_W = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046,
    1.54575, 0.1192, 1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315,
    2.9898, 0.51655, 0.6621,
)
DECAY = -0.5
FACTOR = 19 / 81
TARGET_RETENTION = 0.9
MIN_INTERVAL = 1
MAX_INTERVAL = 3650

RATING_NAMES = {1: "忘了", 2: "模糊", 3: "记得", 4: "简单"}


def _parse_time(value) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text[:len(fmt) + 2], fmt)
        except (ValueError, TypeError):
            continue
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _clamp_difficulty(value: float) -> float:
    return min(10.0, max(1.0, float(value)))


def _init_stability(rating: int, weights=DEFAULT_W) -> float:
    return max(0.1, float(weights[rating - 1]))


def _init_difficulty(rating: int, weights=DEFAULT_W) -> float:
    return _clamp_difficulty(weights[4] - (rating - 3) * weights[5])


def retrievability(elapsed_days: int, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return (1 + FACTOR * max(0, int(elapsed_days)) / stability) ** DECAY


def next_interval(stability: float, retention: float = TARGET_RETENTION) -> int:
    """稳定度 → 天数；90% 记忆率时间隔约等于稳定度。"""
    if stability <= 0:
        return MIN_INTERVAL
    days = (stability / FACTOR) * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL, max(MIN_INTERVAL, round(days))))


def schedule(state: dict | None, rating: int, now: dt.datetime | None = None,
             weights=DEFAULT_W) -> dict:
    """算下一次状态。`state` 是旧 `review_state` 行（None = 新卡）。"""
    if rating not in (1, 2, 3, 4):
        raise ValueError("评分必须是 1–4")
    now = now or dt.datetime.now()
    w = weights
    old = state or {}
    previous = str(old.get("state") or "new")
    stability = float(old.get("stability") or 0)
    difficulty = float(old.get("difficulty") or 0)
    reps = int(old.get("reps") or 0)
    lapses = int(old.get("lapses") or 0)
    last_review = _parse_time(old.get("last_review"))

    if stability <= 0 or previous == "new":
        stability = _init_stability(rating, w)
        difficulty = _init_difficulty(rating, w)
        new_state = "learning" if rating == 1 else "review"
        elapsed = 0
        interval = 1 if rating == 1 else next_interval(stability)
    else:
        if difficulty <= 0:
            difficulty = 5.0
        elapsed = max(0, (now.date() - last_review.date()).days) if last_review else 0
        recall = retrievability(elapsed, stability)
        if rating == 1:
            stability_new = (w[11] * (difficulty ** -w[12])
                             * ((stability + 1) ** w[13] - 1)
                             * math.exp((1 - recall) * w[14]))
            lapses += 1
            new_state = "learning"
        else:
            if elapsed == 0:
                stability_new = stability * math.exp(w[17] * (rating - 3 + w[18]))
            else:
                hard_penalty = w[15] if rating == 2 else 1.0
                easy_bonus = w[16] if rating == 4 else 1.0
                stability_new = stability * (
                    1 + math.exp(w[8]) * (11 - difficulty) * (stability ** -w[9])
                    * (math.exp((1 - recall) * w[10]) - 1)
                    * hard_penalty * easy_bonus)
            new_state = "review"
        stability = max(0.1, stability_new)
        difficulty = _clamp_difficulty(
            w[7] * _init_difficulty(4, w)
            + (1 - w[7]) * (difficulty - w[6] * (rating - 3)))
        interval = 1 if rating == 1 else next_interval(stability)

    reps += 1
    due = (now + dt.timedelta(days=interval)).date().isoformat()
    return {
        "state": new_state,
        "due": due,
        "stability": round(stability, 6),
        "difficulty": round(difficulty, 6),
        "reps": reps,
        "lapses": lapses,
        "last_review": now.strftime("%Y-%m-%d %H:%M:%S"),
        "scheduled_days": int(interval),
        "elapsed_days": int(elapsed),
    }
