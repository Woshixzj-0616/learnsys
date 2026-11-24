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
from learnsys.services.life import items as life_items_service


def _learning(conn, day: str, learning: dict | None = None) -> dict:
    summary = learning or today_service.learning_summary(conn, day)
    plan = summary["plan"]
    return {
        "date": summary["date"],
        "href": summary.get("focus_href") or "#/english",
        "done": plan["done"],
        "total": plan["total"],
        "tier": plan["tier"],
        "tasks": plan["tasks"],
        "due_reviews": summary["due_reviews"],
        "due_sentence": summary.get("due_sentence", 0),
        "due_word": summary.get("due_word", 0),
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
        "href": "#/projects",
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
    items = life_items_service.summary(conn, day)
    # 顺序固定：待办最需要行动，其次订阅、卡片、生活事件。
    reminders: list[str] = life_items_service.reminder_lines(conn, day, limit=2)
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
        "href": "#/life",
        "cards": cards,
        "items": items["items"],
        "subscriptions": subscriptions,
        "events": events,
        "subscription_count": len(subscriptions),
        "event_count": len(events),
        "card_count": len(cards),
        "unread_count": len([item for item in cards if not item.get("read")]),
        "item_count": items["item_count"],
        "overdue_count": items["overdue_count"],
        "due_count": items["due_count"],
        "reminders": reminders,
    }


def payload(conn, day: str = "", learning: dict | None = None) -> dict:
    """三域首页数据：{date, learning, work, life}。空数据也返回完整形状。

    `learning` 可由今日页聚合接口传入，避免重复算今日目标。
    """
    day = str(day or datetime.date.today().isoformat())[:10]
    return {
        "date": day,
        "learning": _learning(conn, day, learning),
        "work": _work(conn),
        "life": _life(conn, day),
    }


# 学习状态里「要不要展开卡点题干」的触发词。只在这里维护一份，
# 避免把「项目/生活/无关英语卡点」塞进 rsync、C++ 这类普通知识题。
_LEARNING_TOPIC_WORDS = (
    "英语", "英文", "写作", "翻译", "作文", "句子", "语法", "冠词", "主谓", "搭配",
    "六级", "听力", "精听", "错题", "错了", "错在", "复习", "生词", "单词", "改错",
)
_CET6_TOPIC_WORDS = ("六级", "听力", "精听", "断点", "循环", "试卷", "长对话", "这句", "这段")
_CODE_MARKERS = (";", "{", "}", "#include", "std::", "()", "=>", "def ", "class ")


def _looks_english(text: str) -> bool:
    """一整句英文（而不是代码/标识符）才当作英语题。"""
    text = str(text or "")
    if any(marker in text for marker in _CODE_MARKERS):
        return False
    words = [item for item in text.replace("\n", " ").split()
             if item.isascii() and any(ch.isalpha() for ch in item)]
    return len(words) >= 6


def _learning_agent_state(conn, day: str, query: str = "") -> str:
    """学习助手专用的状态：只有学习域，卡点按问题相关度决定是否展开。"""
    learning = _learning(conn, day)
    unfinished = [item for item in learning["tasks"] if not item["done"]]
    learn_line = f"学习：今日 {learning['done']}/{learning['total']}"
    if unfinished:
        learn_line += f"；未达标：{unfinished[0].get('slot') or unfinished[0].get('title')}"
    else:
        learn_line += "；三格已完成"
    lines = [
        learn_line,
        f"复习：到期 {learning['due_reviews']} 张"
        f"（句子 {learning.get('due_sentence', 0)} / 单词 {learning.get('due_word', 0)}）",
    ]

    text = str(query or "")
    topical = any(word in text for word in _LEARNING_TOPIC_WORDS) or _looks_english(text)
    wrong = learning["recent_wrong"]
    if wrong and topical:
        lines.append("卡点：")
        lines.extend(
            "- " + " ".join(str(item["question"]).split())[:40]
            for item in wrong[:2])
    elif wrong:
        lines.append(
            f"错题：最近 {len(wrong)} 条待复习（需要时用 recent_wrong_items 查）")
    else:
        lines.append("错题：暂无")

    breakpoint = learning.get("breakpoint")
    if breakpoint and any(word in text for word in _CET6_TOPIC_WORDS):
        lines.append(
            "六级断点："
            f"{breakpoint.get('paper') or '未知试卷'} · "
            f"{breakpoint.get('section') or ''} · "
            f"{breakpoint.get('item') or ''}"
            f"（今天 {int(breakpoint.get('count') or 0)} 次）")
    return clip_personal_state("\n".join(lines))


def agent_state(conn, day: str = "", *, scope: str = "full",
                query: str = "") -> str:
    """给 Agent 的一段 ≤600 字个人状态（顺序固定，空域写「暂无」）。

    默认 `scope="full"` 是工作台三域状态，行为与旧版逐字一致；
    学习助手传 `scope="learning"`：只给学习域，并按本轮问题过滤卡点题干。
    """
    day = str(day or datetime.date.today().isoformat())[:10]
    if str(scope or "full").lower() == "learning":
        return _learning_agent_state(conn, day, query=query)

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
        lines.extend(
            "- " + " ".join(str(item["question"]).split())[:40]
            for item in wrong)
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
