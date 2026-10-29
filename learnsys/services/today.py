"""今日页 / 复盘页的数据装配。

路由只负责鉴权与返回；这里把 store 的查询拼成界面要的形状，
行动卡交给 `services/today_actions.py`（唯一决策点）。
"""
from __future__ import annotations

import datetime

from learnsys import store
from learnsys.knowledge import CATEGORY_NAMES
from learnsys.services import day_plan
from learnsys.services import knowledge as knowledge_service
from learnsys.services import study as study_mod
from learnsys.services import study_time, today_actions
from learnsys.store import asks as ask_store
from learnsys.store import stats


def learning_summary(conn, day: str = "") -> dict:
    """学习域的共用装配：三格 / 到期复习 / 最近卡点 / 六级断点。

    `/api/today` 与个人工作台 `/api/home` 都读这一份，避免两处各查一遍。
    """
    day = day or datetime.date.today().isoformat()
    due = store.wrong_due_items(conn, day)
    recent_wrong = store.recent_wrong_items(conn, limit=3)
    return {
        "date": day,
        "plan": day_plan.build(conn, day, due=due),
        "due_reviews": len(due),
        "due_items": due,
        "recent_wrong": recent_wrong,
        "cet6": stats.cet6_groups(conn, day),
        "breakpoint": stats.latest_cet6_group(conn, day),
    }


def payload(conn, day: str = "") -> dict:
    """一天的学习概况：时长、专注、问答、转写、六级断点、行动卡。"""
    day = day or datetime.date.today().isoformat()
    learning = learning_summary(conn, day)
    recorded = study_time.recorded(conn, day)
    focus_stats = store.focus_stats(conn, day=day)
    recent = store.recent_asks(conn, limit=10, day=day, with_conversation=True)
    return {
        "date": day,
        "study_minutes": recorded["minutes"],
        "study_measured": recorded["measured"],
        "study_estimated": recorded["estimated"],
        "study_breakdown": recorded["breakdown"],
        "activity": recorded["activity"],
        "focus": {
            "minutes": float(focus_stats.get("分钟") or 0),
            "switches": int(focus_stats.get("切换") or 0),
            "apps": [[name, round(float(mins), 1)]
                     for name, mins in (focus_stats.get("程序") or [])],
        },
        "asks": [ask_store.ask_dict(row) for row in recent],
        "ask_count": stats.ask_count(conn, day),
        "transcripts": stats.transcript_totals(conn, day),
        "recordings": store.recording_totals(conn, day=day),
        "due_reviews": learning["due_reviews"],
        "actions": today_actions.build(
            conn, day, learning["due_items"],
            {item["paper_id"] for item in learning["cet6"] if item["paper_id"]}),
        "cet6": learning["cet6"],
    }


def study_payload(conn, focus: str = "", day: str = "") -> dict:
    """复盘 / 测验插件共用的今日素材与提示词（拼题口径只在 `services/study.py`）。

    `focus` 只接受 8 个类目里除「其他」以外的值；其余一律忽略，不拼进提示词。
    """
    day = day or datetime.date.today().isoformat()
    summary_lines: list[str] = []
    for session in stats.sessions_of_day(conn, day):
        sid = session["id"]
        info = store.session_summary(conn, sid)
        line = (f"{str(session['started'])[11:16]} 起记了 {info.get('分钟', 0)} 分钟，"
                f"切了 {info.get('切换', 0)} 次窗口")
        seen: list[str] = []
        for _ts, _process, title in store.session_windows(conn, sid):
            text = (title or "").strip()
            if text and text not in seen:
                seen.append(text)
            if len(seen) >= 8:
                break
        if seen:
            line += "。看过：" + "；".join(seen)
        summary_lines.append(line)

    materials_count = 0
    try:
        for title in stats.module_titles(conn, "netlab", day):
            summary_lines.append(f"完成网工训练：{title}")
        for group in stats.cet6_groups(conn, day):
            summary_lines.append(
                f"六级精听：{group['paper']} / {group['section']} / "
                f"{group['item']}，{group['count']} 个断点")
        train_labels = {"writing": "写作", "translation": "翻译", "sentence": "一句一译"}
        for item in stats.grouped_events(conn, "train", day):
            summary_lines.append(
                f"六级训练：{item['title'] or train_labels.get(item['kind'], item['kind'])}"
                f"（{item['count']} 次）")
        labels = {"open": "打开原文", "ask": "问资料", "quiz": "资料出题"}
        for item in stats.grouped_events(conn, "materials", day):
            materials_count += item["count"]
            summary_lines.append(
                f"资料：{item['title']}（{labels.get(item['kind'], item['kind'])} "
                f"{item['count']} 次）")
    except Exception:
        pass

    transcripts = store.search_transcripts(
        conn, ts_from=f"{day} 00:00:00", ts_to=f"{day} 23:59:59", limit=500)
    digest = study_mod.transcripts_digest(transcripts)
    recent = store.recent_asks(conn, limit=30, day=day)
    asks_preview = [f"问：{(row[1] or '')[:60]}" for row in recent
                    if (row[1] or "").strip()]
    focus_stats = store.focus_stats(conn, day=day)
    weak = knowledge_service.weak_points(
        knowledge_service.attempt_stats(conn)["points"])
    quiz_focus = focus if focus in CATEGORY_NAMES and focus != "其他" else ""
    return {
        "date": day,
        "summary_lines": summary_lines,
        "transcript": digest[-4000:],
        "transcript_chars": len(digest),
        "asks": [ask_store.ask_dict(row) for row in recent],
        "stats": {
            "minutes": focus_stats.get("分钟", 0),
            "switches": focus_stats.get("切换", 0),
            "transcripts": len(transcripts),
            "asks": len(recent),
            "trainings": stats.module_count(conn, "netlab", day),
            "cet6": stats.cet6_count(conn, day),
            "train": stats.module_count(conn, "train", day),
            "materials": materials_count,
        },
        "weak_points": weak,
        "quiz_focus": quiz_focus,
        "review_prompt": study_mod.build_review_question(summary_lines, digest),
        "quiz_prompt": study_mod.build_quiz_question(
            summary_lines, asks_preview, digest,
            weak_points=weak, focus=quiz_focus),
    }
