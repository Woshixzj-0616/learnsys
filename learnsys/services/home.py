"""个人 AI 工作台：学习 / 工作 / 生活三域的唯一装配点。

只装配，不新增业务判定——三格在 `day_plan`、到期复习在 `review`、
行动卡在 `today_actions`。Agent 状态串也在这里生成，由路由层注入，
agent 包只收一段字符串（不得反向 import services）。
"""
from __future__ import annotations

import datetime

from learnsys import store
from learnsys.context import clip_personal_state
from learnsys.services import today as today_service


def _learning(conn, day: str) -> dict:
    summary = today_service.learning_summary(conn, day)
    plan = summary["plan"]
    return {
        "date": summary["date"],
        "href": "#/review" if summary["due_reviews"] else "#/cet6",
        "done": plan["done"],
        "total": plan["total"],
        "tier": plan["tier"],
        "tasks": plan["tasks"],
        "due_reviews": summary["due_reviews"],
        "recent_wrong": [{
            "id": item["id"], "question": item["question"],
            "ts": item["ts"], "next_review": item.get("next_review", ""),
        } for item in summary["recent_wrong"]],
        "cet6": summary["cet6"],
        "breakpoint": summary["breakpoint"],
    }


def _work(conn) -> dict:
    projects = store.list_projects(conn, status="active")
    next_step = next((item["next_step"] for item in projects
                      if item["next_step"]), "")
    return {
        "href": "#/agents",
        "running": store.agent_tasks_running(conn),
        "queued": store.agent_tasks_queued(conn),
        "projects": projects,
        "next_step": next_step,
    }


def _life(conn, day: str) -> dict:
    cards = store.list_cards(conn, day=day, domain="life")
    subscriptions = store.due_subscriptions(conn)
    events = [item for item in store.list_events(conn, module="life", limit=50)
              if str(item.get("ts") or "").startswith(day)]
    reminders: list[str] = []
    for item in subscriptions:
        reminders.append(f"订阅：{item['topic']}")
    for item in events:
        title = str(item.get("title") or "").strip()
        if title:
            reminders.append(f"待办：{title}")
    for item in cards:
        title = str(item.get("title") or "").strip()
        if title:
            reminders.append(f"卡片：{title}")
    return {
        "href": "#/briefing",       # P30 前生活域先进简报；P30 再换 #/life
        "cards": cards,
        "subscriptions": subscriptions,
        "events": events,
        "subscription_count": len(subscriptions),
        "event_count": len(events),
        "reminders": reminders,
    }


def payload(conn, day: str = "") -> dict:
    """三域首页数据：{date, learning, work, life}。空数据也返回完整形状。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    return {
        "date": day,
        "learning": _learning(conn, day),
        "work": _work(conn),
        "life": _life(conn, day),
    }


def agent_state(conn, day: str = "") -> str:
    """给 Agent 的一段 ≤600 字个人状态（顺序固定，空域写「暂无」）。"""
    data = payload(conn, day)
    learning = data["learning"]
    unfinished = [item for item in learning["tasks"] if not item["done"]]
    learn_line = f"学习：今日 {learning['done']}/{learning['total']}"
    if unfinished:
        learn_line += f"；未达标：{unfinished[0].get('slot') or unfinished[0].get('title')}"
    else:
        learn_line += "；三格已完成"
    lines = [learn_line, f"复习：到期 {learning['due_reviews']} 张"]

    wrong = learning["recent_wrong"]
    if wrong:
        lines.append("卡点：")
        lines.extend(f"- {str(item['question']).strip()[:40]}" for item in wrong)
    else:
        lines.append("卡点：暂无")

    projects = data["work"]["projects"][:2]
    if projects:
        lines.append("项目：" + "；".join(
            f"{item['name']} · {item['next_step'] or '暂无下一步'}"
            for item in projects))
    else:
        lines.append("项目：暂无")

    reminders = data["life"]["reminders"][:2]
    lines.append("生活：" + ("；".join(reminders) if reminders else "暂无"))
    return clip_personal_state("\n".join(lines))
