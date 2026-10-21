"""数据接口：今日、学习点、插件事件、检索、错题本、配置、六级上下文。"""
from __future__ import annotations

import datetime
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from learnsys import config as app_config
from learnsys import store
from learnsys.agent.config import load_config
from learnsys.core import db as core_db
from learnsys.server.security import require_token

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
}
LEVEL_TITLES = ["网络小白", "布线学徒", "寻址新手", "路由行者", "抓包侦探",
                "协议解剖师", "拓扑架构师", "网络工程专家", "系统架构师"]


def _conn():
    """测试里可以 monkeypatch 这个函数，换成临时库。"""
    return store.connect()


def _ask_dict(row) -> dict:
    return {
        "ts": row[0], "question": row[1], "answer": row[2],
        "kind": row[3] or "text", "image_path": row[4] or "", "id": row[5],
        "conversation_id": row[6] if len(row) > 6 else None,
    }


@router.get("/api/config")
def get_config(_=Depends(require_token)):
    return load_config().public()


@router.get("/api/today")
def today(_=Depends(require_token)):
    conn = _conn()
    try:
        day = datetime.date.today().isoformat()
        focus = store.focus_stats(conn, day=day)
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
                "minutes": float(focus.get("分钟") or 0),
                "switches": int(focus.get("切换") or 0),
                "apps": [[name, round(float(mins), 1)] for name, mins in (focus.get("程序") or [])],
            },
            "asks": [_ask_dict(row) for row in asks],
            "ask_count": ask_count,
            "transcripts": {"count": int(transcript_count or 0), "chars": int(chars or 0)},
            "due_reviews": len(due),
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
def study_today(_=Depends(require_token)):
    """复盘 / 测验插件共用的今日素材与提示词（拼题口径只在 study.py 一处）。"""
    from learnsys.ask import study as study_mod
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
        except Exception:
            pass
        transcripts = store.search_transcripts(
            conn, ts_from=f"{day} 00:00:00", ts_to=f"{day} 23:59:59", limit=500)
        digest = study_mod.transcripts_digest(transcripts)
        asks = store.recent_asks(conn, limit=30, day=day)
        asks_preview = [f"问：{(row[1] or '')[:60]}" for row in asks if (row[1] or "").strip()]
        focus = store.focus_stats(conn, day=day)
        trainings = int(conn.execute(
            "SELECT COUNT(*) FROM events WHERE module='netlab' AND ts LIKE ?",
            (f"{day}%",)).fetchone()[0] or 0)
        breakpoints = int(conn.execute(
            "SELECT COUNT(*) FROM cet6_events WHERE ts LIKE ?",
            (f"{day}%",)).fetchone()[0] or 0)
        return {
            "date": day,
            "summary_lines": summary_lines,
            "transcript": digest[-4000:],
            "transcript_chars": len(digest),
            "asks": [_ask_dict(row) for row in asks],
            "stats": {
                "minutes": focus.get("分钟", 0),
                "switches": focus.get("切换", 0),
                "transcripts": len(transcripts),
                "asks": len(asks),
                "trainings": trainings,
                "cet6": breakpoints,
            },
            "review_prompt": study_mod.build_review_question(summary_lines, digest),
            "quiz_prompt": study_mod.build_quiz_question(summary_lines, asks_preview, digest),
        }
    finally:
        conn.close()


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
    return {"asks": asks, "starred": starred, "transcripts": transcripts,
            "cet6": cet6, "netlab": netlab, "review": review, "quiz": quiz}


def _xp(counts: dict, focus_minutes: float) -> int:
    return int(counts["asks"] * XP_RULES["ask"]
               + counts["transcripts"] * XP_RULES["transcript"]
               + counts["cet6"] * XP_RULES["cet6"]
               + counts["netlab"] * XP_RULES["netlab"]
               + counts["review"] * XP_RULES["review"]
               + counts["quiz"] * XP_RULES["quiz"]
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
        "WHERE module IN ('netlab', 'review', 'quiz')",
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

        raw = app_config.load_settings()
        try:
            goal = int(raw.get("daily_goal_xp") or app_config.SETTINGS_TEMPLATE["daily_goal_xp"])
        except (TypeError, ValueError):
            goal = 100
        goal = max(20, min(goal, 2000))
        name = str(raw.get("名字") or "").strip()

        return {
            "date": today,
            "name": name,
            "today": {
                "xp": today_xp, "goal": goal,
                "percent": round(min(today_xp, goal) * 100.0 / goal, 1),
                "asks": today_counts["asks"], "minutes": today_focus,
                "cet6": today_counts["cet6"], "netlab": today_counts["netlab"],
                "review": today_counts["review"], "quiz": today_counts["quiz"],
            },
            "total": {"xp": total_xp, **level},
            "streak": streak,
            "week": {"active_days": len(week_days), "minutes": week_minutes,
                     "asks": week_asks},
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


class EventIn(BaseModel):
    module: str = Field(min_length=1, max_length=40)
    kind: str = Field(default="note", max_length=40)
    title: str = Field(default="", max_length=200)
    meta: dict = Field(default_factory=dict)


@router.post("/api/events")
def add_event(req: EventIn, _=Depends(require_token)):
    """插件写一条学习事件（网工训练场完成训练、复盘打卡等）。"""
    conn = _conn()
    try:
        stamp = store.now()
        cur = conn.execute(
            "INSERT INTO events (ts, module, kind, ref_id, title, meta_json) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (stamp, req.module.strip(), req.kind.strip() or "note", req.title.strip(),
             json.dumps(req.meta, ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "id": int(cur.lastrowid or 0), "ts": stamp}
    finally:
        conn.close()


@router.get("/api/events")
def list_events(module: str = "", limit: int = 50, _=Depends(require_token)):
    limit = max(1, min(int(limit or 50), 200))
    conn = _conn()
    try:
        if module:
            rows = conn.execute(
                "SELECT id, ts, module, kind, title, meta_json FROM events "
                "WHERE module = ? ORDER BY id DESC LIMIT ?", (module, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ts, module, kind, title, meta_json FROM events "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        items = []
        for row in rows:
            try:
                meta = json.loads(row[5] or "{}")
            except Exception:
                meta = {}
            items.append({"id": row[0], "ts": row[1], "module": row[2],
                          "kind": row[3], "title": row[4], "meta": meta})
        return {"items": items}
    finally:
        conn.close()


@router.get("/api/search")
def search(q: str = "", limit: int = 20, _=Depends(require_token)):
    if not q.strip():
        return {"query": q, "results": []}
    conn = _conn()
    try:
        return {"query": q, "results": core_db.search(conn, q, limit=limit)}
    finally:
        conn.close()


class WrongAddIn(BaseModel):
    source: str = "manual"          # quiz / manual
    conversation_id: int | None = None
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(default="", max_length=8000)
    my_answer: str = Field(default="", max_length=4000)
    tags: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=8000)


class WrongReviewIn(BaseModel):
    result: str = Field(default="remember", pattern="^(remember|forgot)$")


class WrongMasterIn(BaseModel):
    mastered: bool = True


@router.get("/api/wrongbook")
def wrongbook(status: str = "all", source: str = "", limit: int = 200,
              _=Depends(require_token)):
    conn = _conn()
    try:
        return {
            "items": store.wrong_items(conn, status=status, source=source, limit=limit),
            "counts": store.wrong_counts(conn),
        }
    finally:
        conn.close()


@router.post("/api/wrongbook")
def add_wrongbook(req: WrongAddIn, _=Depends(require_token)):
    """手动补收 / 测验前端补收；同题按来源+指纹去重。"""
    conn = _conn()
    try:
        source = req.source if req.source in ("quiz", "manual") else "manual"
        question = req.question.strip()
        if source == "quiz":
            ref = int(req.conversation_id or 0)
            source_id = f"quiz:{ref}:{store.wrong_fingerprint(question)}"
        else:
            source_id = f"manual:{store.wrong_fingerprint(question)}"
        item_id, created = store.add_wrong_item(
            conn, question=question, answer=req.answer, my_answer=req.my_answer,
            tags=req.tags, note=req.note, source=source, source_id=source_id)
        return {"ok": True, "id": item_id, "created": created,
                "item": store.get_wrong_item(conn, item_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/api/wrongbook/{item_id}/review")
def review_wrongbook(item_id: int, req: WrongReviewIn, _=Depends(require_token)):
    conn = _conn()
    try:
        item = store.review_wrong_item(conn, item_id, req.result)
        if item is None:
            raise HTTPException(status_code=404, detail="这道错题不在了")
        return {"ok": True, "item": item}
    finally:
        conn.close()


@router.post("/api/wrongbook/{item_id}/master")
def master_wrongbook(item_id: int, req: WrongMasterIn, _=Depends(require_token)):
    conn = _conn()
    try:
        if not store.set_wrong_mastered(conn, item_id, req.mastered):
            raise HTTPException(status_code=404, detail="这道错题不在了")
        return {"ok": True, "item": store.get_wrong_item(conn, item_id)}
    finally:
        conn.close()


@router.delete("/api/wrongbook/{item_id}")
def delete_wrongbook(item_id: int, _=Depends(require_token)):
    conn = _conn()
    try:
        if not store.delete_wrong_item(conn, item_id):
            raise HTTPException(status_code=404, detail="这道错题不在了")
        return {"ok": True, "id": item_id}
    finally:
        conn.close()


@router.get("/api/wrongbook/export")
def export_wrongbook(_=Depends(require_token)):
    """全部错题 → Anki CSV（utf-8-sig）。导出是只读操作，走 GET。"""
    from learnsys.ask import study as study_mod
    conn = _conn()
    try:
        items = store.wrong_items(conn, status="all", limit=1000)
        text = study_mod.wrongbook_csv_text(items)
    finally:
        conn.close()
    filename = f"错题本_{datetime.date.today():%Y%m%d}.csv"
    return Response(
        content=("﻿" + text).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.post("/api/wrongbook/{ask_id}/toggle")
def toggle_wrongbook(ask_id: int, _=Depends(require_token)):
    """旧路径保留：问答收藏 = 收进 / 移出错题本。"""
    conn = _conn()
    try:
        state = store.toggle_star(conn, ask_id)
        return {"id": ask_id, "starred": bool(state)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"改错题本失败：{exc}") from exc
    finally:
        conn.close()


@router.get("/api/cet6/context")
def cet6_context(limit: int = 20, _=Depends(require_token)):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ts, paper_title, section, item, sentence, tags, note, loops, plays "
            "FROM cet6_events ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return {"events": [
            {"ts": row[0], "paper": row[1] or "", "section": row[2] or "",
             "item": row[3] or "", "sentence": row[4], "tags": row[5] or "",
             "note": row[6] or "", "loops": int(row[7] or 0),
             "plays": int(row[8] or 0)}
            for row in rows
        ]}
    finally:
        conn.close()


@router.get("/api/cet6/summary")
def cet6_summary(_=Depends(require_token)):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT paper_title, COUNT(*), COUNT(DISTINCT section), MAX(ts) "
            "FROM cet6_events GROUP BY paper_title ORDER BY MAX(ts) DESC").fetchall()
        return {"papers": [
            {"paper": row[0] or "", "breakpoints": int(row[1] or 0),
             "sections": int(row[2] or 0), "last": row[3] or ""}
            for row in rows
        ]}
    finally:
        conn.close()
