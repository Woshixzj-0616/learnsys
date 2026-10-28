"""学习台概览：学习点、等级、连续天数、周统计、成就。"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends

from learnsys import config as app_config
from learnsys import store
from learnsys.server.security import require_token
from learnsys.services import day_plan
from learnsys.services import study_time
from .common import _conn

router = APIRouter()


# 学习点规则：只做“看得见的正反馈”，不改变任何学习数据
XP_RULES = {
    "ask": 10,          # 一条问答
    "transcript": 5,    # 一段课堂转写
    "cet6": 8,          # 一条六级断点
    "netlab": 15,       # 完成一格网工训练
    "review": 25,       # 完成一次今日复盘
    "quiz": 20,         # 开始一场测验（内部对话不落成问答）
    "focus": 1,         # 专注 1 分钟
    "star": 3,          # 收藏一条
    "train_writing": 40,      # 完成一篇写作（限时/练习，不含重批）
    "train_translation": 40,  # 完成一篇整段翻译
    "train_sentence": 5,      # 一句一译提交一次
}
LEVEL_TITLES = ["网络小白", "布线学徒", "寻址新手", "路由行者", "抓包侦探",
                "协议解剖师", "拓扑架构师", "网络工程专家", "系统架构师"]

def _focus_minutes(conn, day: str = "") -> float:
    """专注分钟数：ended_at 缺失的 session 算到此刻（与 focus_stats 同口径）。"""
    end = store.now()
    rows = conn.execute("SELECT started_at, COALESCE(ended_at, '') FROM sessions").fetchall()
    total = 0.0
    for started, ended in rows:
        if day and not str(started).startswith(day):
            continue
        total += max(0.0, store.minutes(started, ended or end))
    return round(total, 1)


def _counts(conn, day: str = "") -> dict:
    """问答 / 转写 / 六级断点 / 收藏的条数（day 为空 = 全量）。"""
    like = f"{day}%" if day else "%"
    asks = int(conn.execute("SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (like,)).fetchone()[0] or 0)
    # 只有显式收题（收藏 / 手动）给学习点；测验判错自动收的不奖励答错。
    starred = int(conn.execute(
        "SELECT COUNT(*) FROM wrong_items WHERE auto = 0 AND ts LIKE ?",
        (like,)).fetchone()[0] or 0)
    transcripts = int(conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE ts_start LIKE ?", (like,)).fetchone()[0] or 0)
    cet6 = int(conn.execute(
        "SELECT COUNT(*) FROM cet6_events WHERE ts LIKE ?", (like,)).fetchone()[0] or 0)
    netlab = int(conn.execute(
        "SELECT COUNT(*) FROM events WHERE module = 'netlab' AND ts LIKE ?", (like,)).fetchone()[0] or 0)
    review = int(conn.execute(
        "SELECT COUNT(*) FROM events WHERE module = 'review' AND kind = 'report' "
        "AND ts LIKE ?", (like,)).fetchone()[0] or 0)
    quiz = int(conn.execute(
        "SELECT COUNT(*) FROM events WHERE module = 'quiz' AND kind = 'quiz' "
        "AND ts LIKE ?", (like,)).fetchone()[0] or 0)
    train = store.event_kind_counts(conn, "train", day=day)
    return {"asks": asks, "starred": starred, "transcripts": transcripts,
            "cet6": cet6, "netlab": netlab, "review": review, "quiz": quiz,
            "train_writing": int(train.get("writing") or 0),
            "train_translation": int(train.get("translation") or 0),
            "train_sentence": int(train.get("sentence") or 0)}


def _xp(counts: dict, focus_minutes: float) -> int:
    return int(counts["asks"] * XP_RULES["ask"]
               + counts["transcripts"] * XP_RULES["transcript"]
               + counts["cet6"] * XP_RULES["cet6"]
               + counts["netlab"] * XP_RULES["netlab"]
               + counts["review"] * XP_RULES["review"]
               + counts["quiz"] * XP_RULES["quiz"]
               + counts["train_writing"] * XP_RULES["train_writing"]
               + counts["train_translation"] * XP_RULES["train_translation"]
               + counts["train_sentence"] * XP_RULES["train_sentence"]
               + int(focus_minutes) * XP_RULES["focus"]
               + counts["starred"] * XP_RULES["star"])


def _level(total_xp: int) -> dict:
    """等级：每级门槛 300、500、700…（逐级 +200），标题走网工成长线。"""
    level, need, rest = 1, 300, int(total_xp)
    while rest >= need and level < 99:
        rest -= need
        level += 1
        need = 300 + (level - 1) * 200
    title = LEVEL_TITLES[min(level - 1, len(LEVEL_TITLES) - 1)]
    return {"level": level, "title": title, "into": rest, "need": need,
            "percent": round(rest * 100.0 / need, 1) if need else 100.0}


def _active_days(conn) -> set[str]:
    days: set[str] = set()
    queries = (
        "SELECT DISTINCT substr(ts, 1, 10) FROM asks",
        "SELECT DISTINCT substr(ts_start, 1, 10) FROM transcripts",
        "SELECT DISTINCT substr(ts, 1, 10) FROM cet6_events",
        "SELECT DISTINCT substr(ts, 1, 10) FROM events "
        "WHERE module IN ('netlab', 'review', 'quiz', 'materials', 'train')",
        "SELECT DISTINCT substr(started_at, 1, 10) FROM sessions",
        "SELECT DISTINCT substr(last_review, 1, 10) FROM wrong_items "
        "WHERE last_review <> ''",
    )
    for sql in queries:
        try:
            for (day,) in conn.execute(sql).fetchall():
                if day:
                    days.add(str(day)[:10])
        except Exception:
            continue
    return days


def _streak(days: set[str]) -> int:
    """从今天（今天没学就从昨天）往前数连续有活动的天数。"""
    cursor = datetime.date.today()
    if cursor.isoformat() not in days:
        cursor -= datetime.timedelta(days=1)
    count = 0
    while cursor.isoformat() in days:
        count += 1
        cursor -= datetime.timedelta(days=1)
    return count


def _achievements(counts_all: dict, streak: int, focus_all: float) -> list[dict]:
    focus_hours = focus_all / 60.0
    defs = [
        ("first_ask", "第一问", "问出第一个问题", counts_all["asks"], 1),
        ("asks_50", "五十问", "累计问过 50 个问题", counts_all["asks"], 50),
        ("asks_200", "两百问", "累计问过 200 个问题", counts_all["asks"], 200),
        ("streak_3", "连续三天", "连续 3 天都有学习记录", streak, 3),
        ("streak_7", "一周不断", "连续 7 天都有学习记录", streak, 7),
        ("streak_30", "月度铁人", "连续 30 天都有学习记录", streak, 30),
        ("cet6_100", "断点猎人", "累计记录 100 条六级断点", counts_all["cet6"], 100),
        ("focus_10h", "十小时专注", "累计专注 10 小时", int(focus_hours), 10),
        ("star_10", "错题十道", "错题本收了 10 道题", counts_all["starred"], 10),
        ("netlab_20", "训练场常客", "完成 20 个网工训练", counts_all["netlab"], 20),
        ("review_1", "第一次复盘", "完成一次今日复盘", counts_all["review"], 1),
        ("quiz_1", "第一次测验", "完成一场自测", counts_all["quiz"], 1),
    ]
    out = []
    for key, name, desc, value, target in defs:
        out.append({"id": key, "name": name, "desc": desc,
                    "value": int(min(value, target)), "target": target,
                    "earned": value >= target})
    return out


@router.get("/api/overview")
def overview(_=Depends(require_token)):
    """学习台首页：学习点、等级、连续天数、周统计、成就、今日目标。"""
    conn = _conn()
    try:
        today = datetime.date.today().isoformat()
        today_counts = _counts(conn, today)
        today_focus = _focus_minutes(conn, today)
        today_xp = _xp(today_counts, today_focus)
        today_recorded = study_time.recorded(conn, today)
        today_plan = day_plan.build(conn, today)

        all_counts = _counts(conn)
        all_focus = _focus_minutes(conn)
        total_xp = _xp(all_counts, all_focus)
        level = _level(total_xp)

        days = _active_days(conn)
        streak = _streak(days)
        week_start = datetime.date.today() - datetime.timedelta(days=6)
        week_days = {d for d in days if d >= week_start.isoformat()}
        week_minutes = _focus_minutes_week(conn, week_start.isoformat())
        week_asks = int(conn.execute(
            "SELECT COUNT(*) FROM asks WHERE substr(ts,1,10) >= ?", (week_start.isoformat(),)
        ).fetchone()[0] or 0)
        week_daily = []
        for offset in range(6, -1, -1):
            day = (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()
            day_recorded = study_time.recorded(conn, day)
            day_check = day_plan.check(conn, day)
            week_daily.append({
                "date": day,
                "minutes": round(_focus_minutes(conn, day), 1),   # 旧口径，保留兼容
                "study_minutes": day_recorded["minutes"],
                "study_measured": day_recorded["measured"],
                "goal_done": day_check["done"],
                "goal_total": day_check["total"],
                "goal_achieved": day_check["met"],
                "active": day in days,
            })
        week_study = round(sum(item["study_minutes"] for item in week_daily), 1)
        week_achieved = sum(1 for item in week_daily if item["goal_achieved"])

        raw = app_config.load_settings()
        try:
            goal = int(raw.get("daily_goal_xp") or app_config.SETTINGS_TEMPLATE["daily_goal_xp"])
        except (TypeError, ValueError):
            goal = 100
        goal = max(20, min(goal, 2000))
        try:
            goal_days = int(raw.get("weekly_goal_days")
                            or app_config.WEEKLY_GOAL_DAYS)
        except (TypeError, ValueError):
            goal_days = app_config.WEEKLY_GOAL_DAYS
        goal_days = max(3, min(goal_days, 7))
        name = str(raw.get("名字") or "").strip()

        return {
            "date": today,
            "name": name,
            "today": {
                # 旧口径（学习点）：保留给等级/兼容调用，不再当今日目标
                "xp": today_xp, "goal": goal,
                "percent": round(min(today_xp, goal) * 100.0 / goal, 1),
                # 今日目标：三格任务完成数（精听 / 训练或复习 / 复盘）
                "goal_tasks": today_plan["tasks"],
                "goal_done": today_plan["done"],
                "goal_total": today_plan["total"],
                "goal_tier": today_plan["tier"],
                "goal_budget_minutes": today_plan["budget_minutes"],
                # 记录时长：实测 + 有上限的估算，只做参考，不参与达标
                "study_minutes": today_recorded["minutes"],
                "study_measured": today_recorded["measured"],
                "study_estimated": today_recorded["estimated"],
                "study_breakdown": today_recorded["breakdown"],
                "activity": today_recorded["activity"],
                "asks": today_counts["asks"], "minutes": today_focus,
                "cet6": today_counts["cet6"], "netlab": today_counts["netlab"],
                "review": today_counts["review"], "quiz": today_counts["quiz"],
                "train": (today_counts["train_writing"]
                          + today_counts["train_translation"]
                          + today_counts["train_sentence"]),
                "train_writing": today_counts["train_writing"],
                "train_translation": today_counts["train_translation"],
                "train_sentence": today_counts["train_sentence"],
            },
            "total": {"xp": total_xp, **level},
            "streak": streak,
            "week": {"active_days": len(week_days), "minutes": week_minutes,
                     "study_minutes": week_study,
                     "achieved_days": week_achieved, "goal_days": goal_days,
                     "asks": week_asks, "daily": week_daily},
            "achievements": _achievements(all_counts, streak, all_focus),
        }
    finally:
        conn.close()


def _focus_minutes_week(conn, since: str) -> float:
    end = store.now()
    rows = conn.execute("SELECT started_at, COALESCE(ended_at, '') FROM sessions").fetchall()
    total = 0.0
    for started, ended in rows:
        if str(started)[:10] < since:
            continue
        total += max(0.0, store.minutes(started, ended or end))
    return round(total, 1)
