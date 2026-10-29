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
import sqlite3
from urllib.parse import quote

from learnsys import store
from learnsys.services import train_plan

TASK_TOTAL = 3
PASS_TASKS = 2      # 两件算达标，第三件（复盘）是加分项
LISTEN_SENTENCES = 3
ASK_OUTPUT_COUNT = 3
LISTEN_MINUTES = 25
REVIEW_MINUTES = 10
REPORT_MINUTES = 10
WRITING_MINUTES = 30
TRANSLATION_MINUTES = 10
WEAK_MINUTES = 10
GENERIC_MINUTES = 15


def _day_like(day: str) -> str:
    return f"{str(day)[:10]}%"


def _safe_rows(conn, sql: str, args=()) -> list:
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _count(conn, sql: str, args=()) -> int:
    rows = _safe_rows(conn, sql, args)
    return int(rows[0][0] or 0) if rows else 0


def _listen_sentences(conn, day: str) -> int:
    """同一段录音里今天标记过的不同句子数（句子号为 0 时退化为题目名）。"""
    rows = _safe_rows(
        conn,
        "SELECT COALESCE(NULLIF(paper_id, ''), COALESCE(paper_title, '')), "
        "COALESCE(section, ''), COALESCE(item, ''), COALESCE(sentence, 0) "
        "FROM cet6_events WHERE ts LIKE ?", (_day_like(day),))
    seen = set()
    for paper, section, item, sentence in rows:
        seen.add((paper, section, item, int(sentence or 0) or str(item)))
    return len(seen)


def _latest_recording(conn) -> dict:
    row = _safe_rows(
        conn,
        "SELECT paper_id, paper_title, section, item FROM cet6_events "
        "ORDER BY ts DESC, id DESC LIMIT 1")
    if not row:
        return {}
    paper_id, paper, section, item = row[0]
    return {"paper_id": paper_id or paper or "", "paper": paper or "六级精听",
            "section": section or "", "item": item or ""}


def _weakest(conn) -> dict | None:
    try:
        from learnsys.services import knowledge as knowledge_service
        weak = knowledge_service.weak_points(
            knowledge_service.attempt_stats(conn)["points"], limit=1)
    except Exception:
        return None
    return weak[0] if weak else None


def check(conn, day: str = "") -> dict:
    """三格是否完成；周视图和历史回放都走这里，保证同一口径。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    train = store.activity_counts(conn, day)
    reviewed = _count(
        conn, "SELECT COUNT(*) FROM review_log WHERE substr(ts, 1, 10) = ?",
        (day,))
    quizzes = _count(
        conn, "SELECT COUNT(*) FROM events WHERE module = 'quiz' "
        "AND kind = 'quiz' AND ts LIKE ?", (_day_like(day),))
    report = _count(
        conn, "SELECT COUNT(*) FROM events WHERE module = 'review' "
        "AND kind = 'report' AND ts LIKE ?", (_day_like(day),))
    listen = _listen_sentences(conn, day)
    asks = _count(conn, "SELECT COUNT(*) FROM asks WHERE ts LIKE ?",
                  (_day_like(day),))
    output = (train["writing"] + train["translation"] + train["sentence"] > 0
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

    latest = _latest_recording(conn)
    if latest:
        title = f"精听 · {latest['paper']}"
        if latest["section"]:
            title += f" / {latest['section']}"
        href = "#/cet6"
        if latest["paper_id"]:
            href += "?paper=" + quote(str(latest["paper_id"]), safe="")
    else:
        title, href = "六级精听 1 段", "#/cet6"
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
    plan = train_plan.plan(conn, day, due=due)
    task = plan.get("task") or {}
    kind = task.get("kind") or ""
    if kind == "review":
        train_title = "复习到期卡"
        due_total = int((plan.get("due") or {}).get("total") or len(due))
        train_detail = f"今天到期 {due_total} 张，复习任意一张即算动过"
        train_href = task.get("href") or "#/review"
        train_minutes = max(5, min(30, round(due_total * 1.2)))
    elif kind == "writing":
        train_title = f"写作 · {task.get('title') or '练习'}"
        train_detail = task.get("detail") or "写完并提交，让 AI 批改"
        train_href = task.get("href") or "#/cet6?tab=writing"
        train_minutes = WRITING_MINUTES
    elif kind == "translation":
        train_title = "翻译 · 一句一译"
        train_detail = task.get("detail") or "写一句英文，提交后立即审核"
        train_href = task.get("href") or "#/cet6?tab=translation"
        train_minutes = TRANSLATION_MINUTES
    else:
        weak = _weakest(conn)
        if weak:
            train_title = f"弱项专练 · {weak['name']}"
            train_detail = (f"掌握度 {int(float(weak.get('mastery') or 0) * 100)}%，"
                            "练 3 道题即算动过")
            train_href = "#/quiz?focus=" + quote(str(weak["name"]), safe="")
            train_minutes = WEAK_MINUTES
        else:
            train_title = "训练或复习"
            train_detail = "写一篇、译一句，或复习任意一张卡"
            train_href = "#/cet6"
            train_minutes = GENERIC_MINUTES
    output_done = state["checks"]["output"]
    if output_done:
        # 已完成时标题说「实际做了什么」，不拿推荐项冒充已完成。
        if counts["writing"]:
            train_title, train_href = "写作 · 今天已完成", "#/cet6?tab=writing"
            train_minutes = WRITING_MINUTES
        elif counts["translation"] or counts["sentence"]:
            train_title, train_href = "翻译 · 今天已完成", "#/cet6?tab=translation"
            train_minutes = TRANSLATION_MINUTES
        elif counts["reviews"]:
            train_title = f"复习 · 今天已复习 {counts['reviews']} 张"
            train_href = "#/wrongbook"
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
    else:
        output_detail = f"{train_detail}；或问 {ASK_OUTPUT_COUNT} 个问题也算"
    output = {
        "id": "output", "slot": "训练 / 复习", "title": train_title,
        "detail": output_detail, "href": train_href, "label": "去做",
        "minutes": train_minutes, "done": output_done,
    }

    report = {
        "id": "report", "slot": "复盘", "title": "复盘今天",
        "detail": ("今天已经复盘过了" if state["checks"]["report"]
                   else "让 AI 读一遍今天的记录，留一段复盘"),
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
