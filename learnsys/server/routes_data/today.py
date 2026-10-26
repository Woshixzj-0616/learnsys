"""今日页与配置：一天的学习概况、问答、六级断点。"""
from __future__ import annotations

import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends

from learnsys import store
from learnsys.llm.config import load_config
from learnsys.knowledge import CATEGORY_NAMES
from learnsys.server.security import require_token
from learnsys.services import knowledge as knowledge_service
from learnsys.services import train_plan
from .common import _ask_dict, _conn

router = APIRouter()


@router.get("/api/config")
def get_config(_=Depends(require_token)):
    return load_config().public()


def _today_actions(conn, day: str, due: list) -> list[dict]:
    """今日页最多三张行动卡：到期复习 / 昨日断点或资料 / 薄弱点去测验。

    口径只在这里拼；前端只负责显示，不再各自判断「今天最该做什么」。
    """
    actions: list[dict] = []
    plan = train_plan.plan(conn, day, due=due)
    train_due = plan["due"]["total"]
    # 到期卡全是写作/翻译错误卡时，直接说人话；混着生词/其他错题才分开列。
    if due and train_due and train_due == len(due):
        actions.append({
            "kind": "train",
            "title": f"六级训练 · {train_due} 张到期错误卡",
            "detail": f"写作 {plan['due']['writing']} 张 · "
                      f"翻译 {plan['due']['translation']} 张",
            "href": "#/wrongbook",
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
    row = conn.execute(
        "SELECT paper_title, section, item, COUNT(*), MAX(paper_id) FROM cet6_events "
        "WHERE ts LIKE ? GROUP BY paper_title, section, item "
        "ORDER BY COUNT(*) DESC, MAX(ts) DESC LIMIT 1", (f"{yesterday}%",)).fetchone()
    if row:
        paper, section, item, count, paper_id = row
        detail = " · ".join(part for part in (paper or "六级", section or "", item or "") if part)
        actions.append({
            "kind": "cet6",
            "title": "接着昨天的听力断点",
            "detail": f"{detail}（{int(count or 0)} 个断点）",
            "href": "#/cet6?paper=" + quote(str(paper_id or paper or ""), safe=""),
            "label": "回到断点",
        })
    else:
        row = conn.execute(
            "SELECT title, COUNT(*) FROM events WHERE module='materials' AND ts LIKE ? "
            "GROUP BY title ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT 1",
            (f"{yesterday}%",)).fetchone()
        if row:
            actions.append({
                "kind": "materials",
                "title": "接着看昨天的资料",
                "detail": f"{row[0] or '资料'}（昨天看过 {int(row[1] or 0)} 次）",
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
        row = conn.execute(
            "SELECT question FROM wrong_items WHERE mastered=0 "
            "ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            question = " ".join(str(row[0] or "").split())[:40]
            actions.append({
                "kind": "weak",
                "title": "薄弱点练一道",
                "detail": f"最近错的：{question}",
                "href": "#/quiz",
                "label": "去测验",
            })
    return actions[:3]


@router.get("/api/today")
def today(_=Depends(require_token)):
    conn = _conn()
    try:
        day = datetime.date.today().isoformat()
        focus_stats = store.focus_stats(conn, day=day)
        asks = store.recent_asks(conn, limit=10, day=day, with_conversation=True)
        ask_count = int(conn.execute(
            "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (f"{day}%",)).fetchone()[0] or 0)
        transcript_count, chars = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts "
            "WHERE ts_start LIKE ?", (f"{day}%",)).fetchone()
        due = store.wrong_due_items(conn, datetime.date.today())
        cet6 = []
        try:
            cet6 = conn.execute(
                "SELECT paper_title, section, item, COUNT(*), MAX(ts), MAX(paper_id) "
                "FROM cet6_events WHERE ts LIKE ? GROUP BY paper_title, section, item "
                "ORDER BY MAX(ts) DESC LIMIT 10", (f"{day}%",)).fetchall()
        except Exception:
            pass
        return {
            "date": day,
            "focus": {
                "minutes": float(focus_stats.get("分钟") or 0),
                "switches": int(focus_stats.get("切换") or 0),
                "apps": [[name, round(float(mins), 1)]
                         for name, mins in (focus_stats.get("程序") or [])],
            },
            "asks": [_ask_dict(row) for row in asks],
            "ask_count": ask_count,
            "transcripts": {"count": int(transcript_count or 0), "chars": int(chars or 0)},
            "recordings": store.recording_totals(conn, day=day),
            "due_reviews": len(due),
            "actions": _today_actions(conn, day, due),
            "cet6": [
                {"paper": row[0] or "", "section": row[1] or "", "item": row[2] or "",
                 "count": int(row[3] or 0), "last": row[4] or "",
                 "paper_id": row[5] or row[0] or ""}
                for row in cet6
            ],
        }
    finally:
        conn.close()


@router.get("/api/study/today")
def study_today(focus: str = "", _=Depends(require_token)):
    """复盘 / 测验插件共用的今日素材与提示词（拼题口径只在 study.py 一处）。

    `focus` 只接受 8 个类目里除「其他」以外的值；其余一律忽略，不拼进提示词。
    """
    from learnsys.services import study as study_mod
    conn = _conn()
    try:
        day = datetime.date.today().isoformat()
        sessions = conn.execute(
            "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions "
            "WHERE started_at LIKE ? ORDER BY id", (f"{day}%",)).fetchall()
        summary_lines = []
        for sid, started, _ended in sessions:
            info = store.session_summary(conn, sid)
            line = (f"{str(started)[11:16]} 起记了 {info.get('分钟', 0)} 分钟，"
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
            for (title,) in conn.execute(
                    "SELECT title FROM events WHERE module='netlab' AND ts LIKE ? "
                    "ORDER BY id DESC LIMIT 10", (f"{day}%",)).fetchall():
                summary_lines.append(f"完成网工训练：{title}")
            for paper, section, item, count in conn.execute(
                    "SELECT paper_title, section, item, COUNT(*) FROM cet6_events "
                    "WHERE ts LIKE ? GROUP BY paper_title, section, item "
                    "ORDER BY MAX(ts) DESC LIMIT 10", (f"{day}%",)).fetchall():
                summary_lines.append(
                    f"六级精听：{paper} / {section} / {item}，{count} 个断点")
            train_labels = {"writing": "写作", "translation": "翻译",
                            "sentence": "一句一译"}
            for kind, title, count in conn.execute(
                    "SELECT kind, title, COUNT(*) FROM events WHERE module='train' "
                    "AND ts LIKE ? GROUP BY kind, title ORDER BY MAX(id) DESC LIMIT 10",
                    (f"{day}%",)).fetchall():
                summary_lines.append(
                    f"六级训练：{title or train_labels.get(kind, kind)}"
                    f"（{int(count or 0)} 次）")
            labels = {"open": "打开原文", "ask": "问资料", "quiz": "资料出题"}
            for kind, title, count in conn.execute(
                    "SELECT kind, title, COUNT(*) FROM events WHERE module='materials' "
                    "AND ts LIKE ? GROUP BY kind, title ORDER BY MAX(id) DESC LIMIT 10",
                    (f"{day}%",)).fetchall():
                materials_count += int(count or 0)
                summary_lines.append(
                    f"资料：{title}（{labels.get(kind, kind)} {int(count or 0)} 次）")
        except Exception:
            pass
        transcripts = store.search_transcripts(
            conn, ts_from=f"{day} 00:00:00", ts_to=f"{day} 23:59:59", limit=500)
        digest = study_mod.transcripts_digest(transcripts)
        asks = store.recent_asks(conn, limit=30, day=day)
        asks_preview = [f"问：{(row[1] or '')[:60]}" for row in asks if (row[1] or "").strip()]
        focus_stats = store.focus_stats(conn, day=day)
        trainings = int(conn.execute(
            "SELECT COUNT(*) FROM events WHERE module='netlab' AND ts LIKE ?",
            (f"{day}%",)).fetchone()[0] or 0)
        breakpoints = int(conn.execute(
            "SELECT COUNT(*) FROM cet6_events WHERE ts LIKE ?",
            (f"{day}%",)).fetchone()[0] or 0)
        train_count = int(conn.execute(
            "SELECT COUNT(*) FROM events WHERE module='train' AND ts LIKE ?",
            (f"{day}%",)).fetchone()[0] or 0)
        weak = knowledge_service.weak_points(
            knowledge_service.attempt_stats(conn)["points"])
        quiz_focus = (focus if focus in CATEGORY_NAMES and focus != "其他" else "")
        return {
            "date": day,
            "summary_lines": summary_lines,
            "transcript": digest[-4000:],
            "transcript_chars": len(digest),
            "asks": [_ask_dict(row) for row in asks],
            "stats": {
                "minutes": focus_stats.get("分钟", 0),
                "switches": focus_stats.get("切换", 0),
                "transcripts": len(transcripts),
                "asks": len(asks),
                "trainings": trainings,
                "cet6": breakpoints,
                "train": train_count,
                "materials": materials_count,
            },
            "weak_points": weak,
            "quiz_focus": quiz_focus,
            "review_prompt": study_mod.build_review_question(summary_lines, digest),
            "quiz_prompt": study_mod.build_quiz_question(
                summary_lines, asks_preview, digest,
                weak_points=weak, focus=quiz_focus),
        }
    finally:
        conn.close()
