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
from learnsys.services.train import coach as train_coach
from learnsys.services.train import plan as train_plan

TASK_TOTAL = 3
PASS_TASKS = 2      # 两件算达标，第三件（复盘）是加分项
LISTEN_SENTENCES = 3
ASK_OUTPUT_COUNT = 3
# 到期卡至少这么多张、且前两天没复习过，才把「复习」提为训练格主推；
# 否则优先推更具体的写作/翻译任务，避免每天都是「复习到期卡」。
REVIEW_URGENT = 20
REVIEW_COOLDOWN_DAYS = 2
LISTEN_MINUTES = 25
REVIEW_MINUTES = 10
REPORT_MINUTES = 10
WRITING_MINUTES = 30
TRANSLATION_MINUTES = 10
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


def _yesterday_summary(conn, day: str) -> str:
    """复盘格副标题：拿昨天的真实记录，别每天都是同一句。"""
    yesterday = (datetime.date.fromisoformat(day)
                 - datetime.timedelta(days=1)).isoformat()
    train = store.activity_counts(conn, yesterday)
    trains = (train["writing"] + train["translation"] + train["sentence"]
              + train["dictation"] + train.get("exam", 0)
              + train.get("chunk", 0))
    reviews = _count(
        conn, "SELECT COUNT(*) FROM review_log WHERE substr(ts, 1, 10) = ?",
        (yesterday,))
    listen = _listen_sentences(conn, yesterday)
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


def _reviewed_recently(conn, day: str,
                       days: int = REVIEW_COOLDOWN_DAYS) -> bool:
    """前两天有没有复习过；有就把「复习」降为备选，避免天天同一张卡。"""
    start = (datetime.date.fromisoformat(day)
             - datetime.timedelta(days=days)).isoformat()
    return _count(
        conn,
        "SELECT COUNT(*) FROM review_log "
        "WHERE substr(ts, 1, 10) >= ? AND substr(ts, 1, 10) < ?",
        (start, day)) > 0


def _review_task(plan: dict, due_total: int) -> dict:
    breakdown = plan.get("due") or {}
    parts = [f"写作 {breakdown[key]} 张" for key in ("writing",)
             if breakdown.get(key)]
    parts += [f"翻译 {breakdown[key]} 张" for key in ("translation",)
              if breakdown.get(key)]
    target = min(due_total, REVIEW_URGENT)
    detail = " · ".join(parts) or "按记忆曲线排到了今天"
    if target < due_total:
        detail += f"（共到期 {due_total} 张）"
    return {
        "id": "review", "kind": "review",
        "title": f"复习 {target} 张到期卡",
        "detail": detail,
        "href": "#/english-review?tab=sentence",
        "label": "去复习",
        "minutes": max(5, min(30, round(target * 1.2))),
    }


def _base_task(task: dict) -> dict | None:
    kind = str((task or {}).get("kind") or "")
    if kind not in ("writing", "translation"):
        return None
    return {
        "id": kind, "kind": kind,
        "title": task.get("title") or ("写作练习" if kind == "writing"
                                       else "一句一译"),
        "detail": task.get("detail") or "",
        "href": task.get("href") or f"#/cet6?tab={kind}",
        "label": task.get("label") or "去做",
        "minutes": WRITING_MINUTES if kind == "writing" else TRANSLATION_MINUTES,
    }


def _dedupe(rows: list[dict]) -> list[dict]:
    """同一入口只留一张卡（「本周整篇」与具体写作题都指向写作页）。"""
    seen: set[str] = set()
    out = []
    for row in rows:
        key = str(row.get("href") or row.get("id") or row.get("kind") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _alternatives(conn, day: str, plan: dict, review_task: dict | None,
                  due_total: int) -> list[dict]:
    """训练格备选：主推一条，其余给「换一个」。

    到期卡只在「≥20 张且前两天没复习」时提到第一位；
    否则先推二稿、弱项技能、写作/翻译，复习放后面。
    """
    coach_rows = []
    for row in train_coach.candidates(conn, day):
        item = dict(row)
        item.setdefault("id", str(row.get("kind") or ""))
        item.setdefault("minutes", GENERIC_MINUTES)
        coach_rows.append(item)
    rows: list[dict] = []
    if (review_task and due_total >= REVIEW_URGENT
            and not _reviewed_recently(conn, day)):
        rows.append(review_task)
    rows.extend(row for row in coach_rows
                if row.get("kind") in ("rewrite", "skill"))
    base = _base_task(train_plan.next_task(conn, plan.get("today") or {}))
    if base:
        rows.append(base)
    rows.extend(row for row in coach_rows if row.get("kind") == "whole")
    if review_task and not any(row.get("id") == "review" for row in rows):
        rows.append(review_task)
    return _dedupe(rows)[:4]


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
    due_total = int((plan.get("due") or {}).get("total") or len(due))
    review_task = _review_task(plan, due_total) if due_total else None
    output_done = state["checks"]["output"]
    alternatives: list[dict] = []
    if not output_done:
        alternatives = _alternatives(conn, day, plan, review_task, due_total)
        primary = alternatives[0] if alternatives else None
        if primary:
            train_title = primary["title"]
            train_href = primary["href"]
            train_minutes = int(primary["minutes"] or GENERIC_MINUTES)
            output_detail = (f"{primary['detail']}；或问 {ASK_OUTPUT_COUNT} 个问题也算")
        else:
            train_title = "训练或复习"
            train_detail = "写一篇、译一句，或复习任意一张卡"
            train_href = "#/cet6"
            train_minutes = GENERIC_MINUTES
            output_detail = f"{train_detail}；或问 {ASK_OUTPUT_COUNT} 个问题也算"
    if output_done:
        # 已完成时标题说「实际做了什么」，不拿推荐项冒充已完成。
        if counts["writing"]:
            train_title, train_href = "写作 · 今天已完成", "#/cet6?tab=writing"
            train_minutes = WRITING_MINUTES
        elif counts["translation"] or counts["sentence"]:
            train_title, train_href = "翻译 · 今天已完成", "#/cet6?tab=translation"
            train_minutes = TRANSLATION_MINUTES
        elif counts.get("dictation"):
            train_title = f"专项听写 · 今天已完成 {counts['dictation']} 句"
            train_href = "#/cet6?tab=drill"
            train_minutes = max(5, min(30, round(counts["dictation"] * 2)))
        elif counts.get("chunk"):
            train_title = f"意群长句 · 今天已完成 {counts['chunk']} 句"
            train_href = "#/cet6?tab=drill&mode=chunk"
            train_minutes = max(5, min(30, round(counts["chunk"] * 3)))
        elif counts.get("exam"):
            train_title = f"真题自评 · 今天已完成 {counts['exam']} 段"
            train_href = "#/cet6?tab=drill&mode=exam"
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
