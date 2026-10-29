"""今日页行动卡：最多三张——到期复习 / 昨日断点或资料 / 薄弱点去测验。

口径只在这里拼；前端只负责显示，不再各自判断「今天最该做什么」。
路由层不再参与决策，只把 `build()` 的结果原样返回。
"""
from __future__ import annotations

import datetime
from urllib.parse import quote

from learnsys.services import knowledge as knowledge_service
from learnsys.services import train_plan
from learnsys.store import stats


def build(conn, day: str, due: list,
          today_papers: set[str] | None = None) -> list[dict]:
    """生成行动卡。

    `today_papers` 是今天已经出现过的试卷 id：同一份卷子不再重复发「接着昨天」卡，
    首页的「接着上次」已经承担这个入口。
    """
    actions: list[dict] = []
    today_papers = today_papers or set()
    plan = train_plan.plan(conn, day, due=due)
    train_due = plan["due"]["total"]
    # 到期卡全是写作/翻译错误卡时，直接说人话；混着生词/其他错题才分开列。
    if due and train_due and train_due == len(due):
        actions.append({
            "kind": "train",
            "title": f"六级训练 · {train_due} 张到期错误卡",
            "detail": f"写作 {plan['due']['writing']} 张 · "
                      f"翻译 {plan['due']['translation']} 张",
            "href": "#/cet6?tab=review",
            "label": "去复习",
        })
    elif due:
        actions.append({
            "kind": "due",
            "title": f"{len(due)} 条到期",
            "detail": "错题和生词按记忆曲线排到了今天",
            "href": "#/wrongbook",
            "label": "去复习",
        })
    if (not train_due or train_due != len(due)) and plan["today"]["total"] == 0 \
            and plan["task"] and plan["task"]["kind"] != "review":
        task = plan["task"]
        actions.append({
            "kind": "train",
            "title": f"六级训练 · {task['title']}",
            "detail": task["detail"],
            "href": task["href"],
            "label": task["label"],
        })

    yesterday = (datetime.date.fromisoformat(day)
                 - datetime.timedelta(days=1)).isoformat()
    cet6 = stats.latest_cet6_group(conn, yesterday)
    if cet6:
        paper_key = str(cet6["paper_id"] or cet6["paper"] or "")
        if paper_key not in today_papers:
            detail = " · ".join(part for part in
                                (cet6["paper"] or "六级", cet6["section"] or "",
                                 cet6["item"] or "") if part)
            actions.append({
                "kind": "cet6",
                "title": "接着昨天的听力断点",
                "detail": f"{detail}（{cet6['count']} 个断点）",
                "href": "#/cet6?paper=" + quote(paper_key, safe=""),
                "label": "回到断点",
            })
    else:
        material = stats.latest_material_event(conn, yesterday)
        if material:
            actions.append({
                "kind": "materials",
                "title": "接着看昨天的资料",
                "detail": f"{material['title'] or '资料'}（昨天看过 {material['count']} 次）",
                "href": "#/materials",
                "label": "打开资料",
            })

    weak = knowledge_service.weak_points(
        knowledge_service.attempt_stats(conn)["points"], limit=1)
    weakest = weak[0] if weak else None
    if weakest:
        actions.append({
            "kind": "weak",
            "title": f"薄弱点练一道 · {weakest['name']}",
            "detail": f"掌握度 {int(float(weakest['mastery']) * 100)}%，"
                      f"{weakest['attempts']} 条答题",
            "href": "#/quiz?focus=" + quote(weakest["name"], safe=""),
            "label": "练这类",
        })
    else:
        question = " ".join(stats.latest_unmastered_question(conn).split())[:40]
        if question:
            actions.append({
                "kind": "weak",
                "title": "薄弱点练一道",
                "detail": f"最近错的：{question}",
                "href": "#/quiz",
                "label": "去测验",
            })
    return actions[:3]
