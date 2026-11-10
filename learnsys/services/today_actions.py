"""今日页行动卡：从 `agenda` 候选池里取「也可以」做的事，最多三张。

这里不再另排一套优先级；默认主推由 `day_plan` 的训练格承担，
行动卡跳过同一个 `href`，只给备选。
"""
from __future__ import annotations

from learnsys.services.train import agenda


def _card(row: dict) -> dict:
    return {
        "kind": row.get("kind", ""),
        "title": row.get("title", ""),
        "detail": row.get("detail", ""),
        "href": row.get("href", ""),
        "label": row.get("label", "去看看"),
    }


def build(conn, day: str, due: list,
          today_papers: set[str] | None = None,
          exclude_href: str = "") -> list[dict]:
    """生成行动卡；`exclude_href` 是今天训练格主推的入口，避免重复。"""
    rows = agenda.candidates(conn, day, due=due, today_papers=today_papers)
    actions: list[dict] = []
    for row in rows:
        if row.get("kind") not in agenda.EXTRA_KINDS:
            continue
        if row.get("href") == exclude_href:
            continue
        actions.append(_card(row))
        if len(actions) >= 3:
            return actions
    for row in rows:
        if row.get("kind") not in agenda.OUTPUT_KINDS:
            continue
        if row.get("href") == exclude_href:
            continue
        actions.append(_card(row))
        if len(actions) >= 3:
            break
    return actions
