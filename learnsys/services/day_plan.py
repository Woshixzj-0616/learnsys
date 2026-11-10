"""今日计划：三格目标的唯一口径。

目标不再按「投入多少分钟」判定；每格完成条件都是数据库事实：

1. **精听**：今天在同一段录音上标记了 ≥3 个不同句子
   （按 188 次断点也只算一次，避免按键刷时长）。
2. **训练 / 复习 / 问答**：今天有写作/翻译提交、任意一次复习、
   任意一次测验，或问了 ≥3 个问题。
3. **复盘**：今天完成过一次「今日复盘」。

两件算达标，第三件（复盘）是加分项；这样不会因为最后一件没做就判「没达标」。

时间只做预算：`budget_minutes` 是三格预计用时相加，不参与达标判定。
周视图复用 `check()`，不另写一套判断。
"""
from __future__ import annotations

import datetime
from urllib.parse import quote

from learnsys import store
from learnsys.services.train import agenda
from learnsys.store import stats as store_stats

TASK_TOTAL = 3
PASS_TASKS = 2      # 两件算达标，第三件（复盘）是加分项
LISTEN_SENTENCES = 3
ASK_OUTPUT_COUNT = 3
LISTEN_MINUTES = 25
REVIEW_MINUTES = 10
REPORT_MINUTES = 10
WRITING_MINUTES = 30
TRANSLATION_MINUTES = 10
GENERIC_MINUTES = 15


def _alternatives(conn, day: str, due: list | None) -> list[dict]:
    """训练格候选：由 `agenda` 统一排序，这里只保留输出格能用的类型。"""
    return [row for row in agenda.candidates(conn, day, due=due)
            if row.get("kind") in agenda.OUTPUT_KINDS][:4]


def _yesterday_summary(conn, day: str) -> str:
    """复盘格副标题：拿昨天的真实记录，别每天都是同一句。"""
    yesterday = (datetime.date.fromisoformat(day)
                 - datetime.timedelta(days=1)).isoformat()
    train = store.activity_counts(conn, yesterday)
    trains = (train["writing"] + train["translation"] + train["sentence"]
              + train["dictation"] + train.get("exam", 0)
              + train.get("chunk", 0))
    reviews = store_stats.count_review_log(conn, yesterday)
    listen = store_stats.listen_sentences(conn, yesterday)
    parts = []
    if listen:
        parts.append(f"精听 {listen} 句")
    if trains:
        parts.append(f"训练 {trains} 次")
    if reviews:
        parts.append(f"复习 {reviews} 张")
    if not parts:
        return "昨天没有学习记录；今天做完一件再复盘"
    return "昨天 " + " · ".join(parts) + "；今天挑一件写清楚"


def check(conn, day: str = "") -> dict:
    """三格是否完成；周视图和历史回放都走这里，保证同一口径。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    train = store.activity_counts(conn, day)
    reviewed = store_stats.count_review_log(conn, day)
    quizzes = store_stats.count_events(conn, "quiz", "quiz", day)
    report = store_stats.count_events(conn, "review", "report", day)
    listen = store_stats.listen_sentences(conn, day)
    asks = store_stats.count_asks(conn, day)
    output = (train["writing"] + train["translation"] + train["sentence"]
              + train["dictation"] + train.get("exam", 0)
              + train.get("chunk", 0) > 0
              or reviewed > 0 or quizzes > 0 or asks >= ASK_OUTPUT_COUNT)
    checks = {
        "listen": listen >= LISTEN_SENTENCES,
        "output": output,
        "report": report >= 1,
    }
    done = sum(1 for value in checks.values() if value)
    return {
        "date": day,
        "done": done,
        "total": TASK_TOTAL,
        "met": done >= PASS_TASKS,
        "checks": checks,
        "counts": {
            "listen_sentences": listen,
            "writing": int(train["writing"]),
            "translation": int(train["translation"]),
            "sentence": int(train["sentence"]),
            "dictation": int(train["dictation"]),
            "exam": int(train.get("exam", 0)),
            "chunk": int(train.get("chunk", 0)),
            "asks": asks,
            "reviews": reviewed,
            "quizzes": quizzes,
            "reports": report,
        },
    }


def build(conn, day: str = "", due: list | None = None) -> dict:
    """今日三格：精听 / 训练或复习 / 复盘。

    每格带 `done`、`detail`（人话进度）和 `minutes`（预算估算）。
    预算只用于「今天大概要花多久」，不改完成判定。
    `due` 可由调用方传入已查好的到期列表（首页装配不重复查）。
    """
    day = str(day or datetime.date.today().isoformat())[:10]
    state = check(conn, day)
    counts = state["counts"]

    latest = store_stats.latest_recording(conn)
    if latest:
        title = f"精听 · {latest['paper']}"
        if latest["section"]:
            title += f" / {latest['section']}"
        href = "#/english?tab=listening"
        if latest["paper_id"]:
            href += "&paper=" + quote(str(latest["paper_id"]), safe="")
    else:
        title, href = "六级精听 1 段", "#/english?tab=listening"
    if state["checks"]["listen"]:
        listen_detail = f"今天已标记 {counts['listen_sentences']} 个不同句子"
    else:
        listen_detail = (f"今天 {counts['listen_sentences']} 个不同句子，"
                         f"达到 {LISTEN_SENTENCES} 个即完成")
    listen = {
        "id": "listen", "slot": "精听", "title": title,
        "detail": listen_detail, "href": href, "label": "去精听",
        "minutes": LISTEN_MINUTES, "done": state["checks"]["listen"],
    }

    if due is None:
        due = store.wrong_due_items(conn, day)
    output_done = state["checks"]["output"]
    alternatives: list[dict] = []
    if not output_done:
        alternatives = _alternatives(conn, day, due)
        primary = alternatives[0] if alternatives else None
        if primary:
            train_title = primary["title"]
            train_href = primary["href"]
            train_minutes = int(primary["minutes"] or GENERIC_MINUTES)
            output_detail = (f"{primary['detail']}；或问 {ASK_OUTPUT_COUNT} 个问题也算")
        else:
            train_title = "训练或复习"
            train_detail = "写一篇、译一句，或复习任意一张卡"
            train_href = "#/english"
            train_minutes = GENERIC_MINUTES
            output_detail = f"{train_detail}；或问 {ASK_OUTPUT_COUNT} 个问题也算"
    if output_done:
        # 已完成时标题说「实际做了什么」，不拿推荐项冒充已完成。
        if counts["writing"]:
            train_title, train_href = "写作 · 今天已完成", "#/english?tab=writing"
            train_minutes = WRITING_MINUTES
        elif counts["translation"] or counts["sentence"]:
            train_title, train_href = ("翻译 · 今天已完成",
                                       "#/english?tab=writing&sub=translation")
            train_minutes = TRANSLATION_MINUTES
        elif counts.get("dictation"):
            train_title = f"专项听写 · 今天已完成 {counts['dictation']} 句"
            train_href = "#/english?tab=listening"
            train_minutes = max(5, min(30, round(counts["dictation"] * 2)))
        elif counts.get("chunk"):
            train_title = f"意群长句 · 今天已完成 {counts['chunk']} 句"
            train_href = "#/english?tab=listening"
            train_minutes = max(5, min(30, round(counts["chunk"] * 3)))
        elif counts.get("exam"):
            train_title = f"真题自评 · 今天已完成 {counts['exam']} 段"
            train_href = "#/english?tab=listening"
            train_minutes = max(5, min(60, counts["exam"] * 10))
        elif counts["reviews"]:
            train_title = f"复习 · 今天已复习 {counts['reviews']} 张"
            train_href = "#/english-review"
            train_minutes = max(5, min(30, round(counts["reviews"] * 1.2)))
        elif counts["quizzes"]:
            train_title = f"测验 · 今天开了 {counts['quizzes']} 场"
            train_href = "#/quiz"
            train_minutes = max(5, min(15, round(counts["quizzes"] * 5)))
        else:
            train_title = f"问答 · 今天问了 {counts['asks']} 个问题"
            train_href = "#/ask"
            train_minutes = max(5, min(20, counts["asks"] * 2))
        output_detail = "今天已经动过训练、复习或问答"
    output = {
        "id": "output", "slot": "训练 / 复习", "title": train_title,
        "detail": output_detail, "href": train_href, "label": "去做",
        "minutes": train_minutes, "done": output_done,
        "alternatives": alternatives,
    }

    report = {
        "id": "report", "slot": "复盘", "title": "复盘今天",
        "detail": ("今天已经复盘过了" if state["checks"]["report"]
                   else _yesterday_summary(conn, day)),
        "href": "#/review", "label": "去复盘",
        "minutes": REPORT_MINUTES, "done": state["checks"]["report"],
    }

    tasks = [listen, output, report]
    done = sum(1 for item in tasks if item["done"])
    if done >= len(tasks):
        tier = "done"
    elif done >= PASS_TASKS:
        tier = "met"
    elif done:
        tier = "floor"
    else:
        tier = "none"
    return {
        "date": day,
        "tasks": tasks,
        "done": done,
        "total": len(tasks),
        "tier": tier,
        "budget_minutes": sum(int(item["minutes"] or 0) for item in tasks),
        "checks": state["checks"],
        "counts": counts,
    }
