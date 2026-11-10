"""写作/翻译提升提醒：每天最多一条（唯一决策点）。

候选池在 `agenda.py`；这里只负责「今天要不要提醒、提醒哪一条」：

1. 最近整篇还没写二稿 → 推二稿（即使今天已经练过，也先把上次收口）；
2. 今天已经动过写作/翻译 → 不再提醒；
3. 否则取候选池里第一条写作/翻译项（弱项技能 → 本周整篇）。

不碰听力、听写和普通复习：提醒多了等于没提醒。
"""
from __future__ import annotations

import datetime

from learnsys.services.train import agenda
from learnsys.services.train import plan as train_plan


def candidates(conn, day: str = "") -> list[dict]:
    """写作/翻译候选，按 `agenda` 的优先级排序。"""
    return agenda.coach_candidates(conn, day)


def build(conn, day: str = "") -> dict | None:
    """返回今天唯一一条写作/翻译提醒；没有就返回 None。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    rows = candidates(conn, day)
    if not rows:
        return None
    # 二稿优先：即使今天已经练过，也先把上次的整篇收口。
    if rows[0].get("kind") == "rewrite":
        return rows[0]
    today = train_plan.today_activity(conn, day)
    if today.get("writing") or today.get("translation") or today.get("sentence"):
        return None
    return rows[0]
