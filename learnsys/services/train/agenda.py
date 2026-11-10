"""今日学习候选池（唯一优先级落点）。

只回答一个问题：今天按优先级有哪些可做的事。各界面只在自己的候选里切片，
不再各自排一套优先级：

- `day_plan` 取 `OUTPUT_KINDS` 填「训练 / 复习」格；
- `today_actions` 取 `EXTRA_KINDS` 填行动卡；
- `coach` 取 `COACH_KINDS` 给写作/翻译提醒；
- `home` 用第一条的输出格 `href` 作为学习域入口。

优先级：到期复习（≥20 张且前两天没复习）→ 二稿 → 弱项技能 → 当天未练科目
→ 少量到期复习 → 本周整篇 → 听力断点 / 昨天资料 → 薄弱点。
"""
from __future__ import annotations

import datetime
import json
from urllib.parse import quote

from learnsys import store
from learnsys.services import knowledge as knowledge_service
from learnsys.services.train import plan as train_plan
from learnsys.services.train import stats as train_stats
from learnsys.services.train import submissions as service
from learnsys.store import stats as store_stats
from learnsys.store import train as train_store
from learnsys.train import content

REVIEW_URGENT = 20
REVIEW_COOLDOWN_DAYS = 2
REWRITE_WINDOW_DAYS = 30
TAB = {"writing": "writing", "translation": "translation"}
OUTPUT_KINDS = ("review", "rewrite", "skill", "writing", "translation")
COACH_KINDS = ("rewrite", "skill", "whole")
EXTRA_KINDS = ("review", "cet6", "weak", "materials")

SKILL_BY_ERROR = {
    "术语": "文化术语",
    "文化": "文化术语",
    "误译": "增补省译",
    "漏译": "增补省译",
    "改变原意": "增补省译",
    "搭配": "词性转换",
    "用词": "词性转换",
    "词性": "词性转换",
    "语法": "主干识别",
    "中式英语": "主干识别",
    "拼写": "主干识别",
    "结构": "长句拆分",
    "长句": "长句拆分",
    "语序": "语序调整",
    "指代": "指代一致",
}


def _review(row: dict) -> dict:
    try:
        data = json.loads(row.get("band_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _prompt_title(kind: str, prompt_id: str) -> str:
    pack = content.pack(kind, prompt_id)
    return str((pack or {}).get("title") or prompt_id)


def _latest_without_rewrite(conn, day: str) -> dict | None:
    """最近 30 天里，第一条还没有二稿的整篇提交。"""
    floor = (datetime.date.fromisoformat(day)
             - datetime.timedelta(days=REWRITE_WINDOW_DAYS)).isoformat()
    for row in train_store.recent_whole_submissions(conn, limit=20):
        created = str(row.get("created_at") or "")[:10]
        if created and created < floor:
            break
        if train_store.has_rewrite(conn, int(row["id"])):
            continue
        return row
    return None


def _rewrite_action(row: dict) -> dict:
    kind = str(row.get("kind") or "writing")
    review = _review(row)
    task = str(review.get("rewrite_task") or "").strip()
    if not task:
        task = "；".join(str(x) for x in (review.get("priorities") or [])[:2])
    title = f"给《{_prompt_title(kind, row.get('prompt_id') or '')}》写二稿"
    return {
        "id": "rewrite", "kind": "rewrite", "slot": "output",
        "title": title,
        "detail": (task or "只改上次批改点名的 3 处，其余不动")[:80],
        "href": (f"#/english?tab={TAB.get(kind, 'writing')}"
                 f"&submission={row['id']}&rewrite=1"),
        "label": "写二稿",
        "minutes": 30 if kind == "writing" else 10,
        "reason": "上次整篇还没重写",
        "prompt_id": row.get("prompt_id") or "",
        "submission_id": row["id"],
    }


def _top_error(conn) -> tuple[str, int, str] | None:
    data = train_stats.stats(conn, days=30)
    for row in data.get("error_types") or []:
        kind = str(row.get("type") or "").strip()
        skill = SKILL_BY_ERROR.get(kind)
        count = int(row.get("count") or 0)
        if skill and count > 0:
            return kind, count, skill
    return None


def _skill_action(kind: str, count: int, skill: str) -> dict:
    return {
        "id": "skill", "kind": "skill", "slot": "output",
        "title": f"专项：{skill} 10 句",
        "detail": f"近 30 天「{kind}」错 {count} 次，是当前最大的扣分项",
        "href": "#/english?tab=translation&skill=" + quote(skill, safe=""),
        "label": "去练 10 句",
        "minutes": 10,
        "reason": f"错误画像：{kind}",
        "skill": skill,
    }


def _base_candidate(task: dict) -> dict | None:
    kind = str((task or {}).get("kind") or "")
    if kind not in ("writing", "translation"):
        return None
    return {
        "id": kind, "kind": kind, "slot": "output",
        "title": task.get("title") or ("写作练习" if kind == "writing"
                                       else "一句一译"),
        "detail": task.get("detail") or "",
        "href": task.get("href") or f"#/english?tab={kind}",
        "label": task.get("label") or "去做",
        "minutes": 30 if kind == "writing" else 10,
        "reason": "今天还没练这一科",
    }


def _review_candidate(conn, due: list[dict], day: str) -> dict | None:
    if not due:
        return None
    train_due = [row for row in due
                 if row.get("source") in train_plan.TRAIN_SOURCES]
    count = len(train_due) or len(due)
    target = min(count, REVIEW_URGENT)
    writing = sum(1 for row in train_due if row.get("source") == "writing")
    translation = sum(1 for row in train_due if row.get("source") == "translation")
    parts = []
    if writing:
        parts.append(f"写作 {writing} 张")
    if translation:
        parts.append(f"翻译 {translation} 张")
    detail = " · ".join(parts) if parts else "句子和单词按记忆曲线排到了今天"
    if target < count:
        detail += f"（共到期 {count} 张）"
    return {
        "id": "review", "kind": "review", "slot": "output",
        "title": f"复习 {target} 张到期卡",
        "detail": detail,
        "href": "#/english-review?tab=sentence",
        "label": "去复习",
        "minutes": max(5, min(30, round(target * 1.2))),
        "reason": "到期复习",
        "due_total": count,
    }


def _review_is_urgent(conn, day: str, candidate: dict) -> bool:
    return (int(candidate.get("due_total") or 0) >= REVIEW_URGENT
            and not store_stats.reviewed_since(conn, day, REVIEW_COOLDOWN_DAYS))


def _week_whole_count(conn, day: str) -> int:
    today = datetime.date.fromisoformat(day)
    monday = (today - datetime.timedelta(days=today.weekday())).isoformat()
    return train_store.week_whole_count(conn, monday)


def _whole_action(conn) -> dict:
    items = service.list_prompts(conn, "writing").get("items") or []
    fresh = next((item for item in items if not item.get("done")), None)
    fresh = fresh or (items[0] if items else {})
    detail = (f"{fresh.get('title') or '写作'} · "
              f"{fresh.get('minutes') or 30} 分钟 · 写完直接批改")
    return {
        "id": "whole", "kind": "whole", "slot": "output",
        "title": "本周还没写整篇",
        "detail": detail,
        "href": "#/english?tab=writing",
        "label": "开始整篇",
        "minutes": 30,
        "reason": "本周整篇数为 0",
    }


def _listen_candidate(conn, day: str, today_papers: set | None) -> dict | None:
    yesterday = (datetime.date.fromisoformat(day)
                 - datetime.timedelta(days=1)).isoformat()
    group = store_stats.latest_cet6_group(conn, yesterday)
    if group:
        key = str(group.get("paper_id") or group.get("paper") or "")
        if key not in (today_papers or set()):
            detail = " · ".join(part for part in
                                (group.get("paper") or "六级",
                                 group.get("section") or "",
                                 group.get("item") or "") if part)
            return {
                "id": "listen", "kind": "cet6", "slot": "extra",
                "title": "接着昨天的听力断点",
                "detail": f"{detail}（{group.get('count', 0)} 个断点）",
                "href": "#/english?tab=listening&paper=" + quote(key, safe=""),
                "label": "回到断点",
                "minutes": 25,
                "reason": "昨天听到一半",
            }
    material = store_stats.latest_material_event(conn, yesterday)
    if material:
        return {
            "id": "material", "kind": "materials", "slot": "extra",
            "title": "接着看昨天的资料",
            "detail": f"{material.get('title') or '资料'}（昨天看过 "
                      f"{material.get('count', 0)} 次）",
            "href": "#/materials",
            "label": "打开资料",
            "minutes": 15,
            "reason": "昨天看过的资料",
        }
    return None


def _weak_candidate(conn) -> dict | None:
    try:
        points = knowledge_service.attempt_stats(conn)["points"]
        weak = knowledge_service.weak_points(points, limit=1)
    except Exception:  # noqa: BLE001 - 旧库/空库没有知识点表时不影响今日计划
        weak = []
    if weak:
        item = weak[0]
        return {
            "id": "weak", "kind": "weak", "slot": "extra",
            "title": f"薄弱点练一道 · {item['name']}",
            "detail": f"掌握度 {int(float(item['mastery']) * 100)}%，"
                      f"{item['attempts']} 条答题",
            "href": "#/quiz?focus=" + quote(item["name"], safe=""),
            "label": "练这类",
            "minutes": 10,
            "reason": "掌握度最低",
        }
    question = " ".join(store_stats.latest_unmastered_question(conn).split())[:40]
    if not question:
        return None
    return {
        "id": "weak", "kind": "weak", "slot": "extra",
        "title": "薄弱点练一道",
        "detail": f"最近错的：{question}",
        "href": "#/quiz",
        "label": "去测验",
        "minutes": 10,
        "reason": "最近错题",
    }


def _dedupe(rows: list[dict]) -> list[dict]:
    """同一入口只留一张卡；不同 kind 但同 href 的保留，交给各界面过滤。"""
    seen: set[tuple[str, str]] = set()
    out = []
    for row in rows:
        key = (str(row.get("id") or ""), str(row.get("href") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def candidates(conn, day: str = "", due: list | None = None,
               today_papers: set | None = None) -> list[dict]:
    """今天可做的事，按优先级排序；第一项是默认主推。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    if due is None:
        due = store.wrong_due_items(conn, day)
    today = train_plan.today_activity(conn, day)
    rows: list[dict] = []
    review = _review_candidate(conn, due, day)
    if review and _review_is_urgent(conn, day, review):
        rows.append(review)
    whole = _latest_without_rewrite(conn, day)
    if whole:
        rows.append(_rewrite_action(whole))
    weak = _top_error(conn)
    if weak:
        rows.append(_skill_action(*weak))
    base = train_plan.next_task(conn, today)
    if base:
        candidate = _base_candidate(base)
        if candidate:
            rows.append(candidate)
    if review and not any(row.get("id") == "review" for row in rows):
        rows.append(review)
    if _week_whole_count(conn, day) < 1:
        rows.append(_whole_action(conn))
    extra = _listen_candidate(conn, day, today_papers)
    if extra:
        rows.append(extra)
    weak_point = _weak_candidate(conn)
    if weak_point:
        rows.append(weak_point)
    return _dedupe(rows)


def coach_candidates(conn, day: str = "") -> list[dict]:
    """写作/翻译提升项；`coach.build()` 只取第一条。"""
    return [row for row in candidates(conn, day)
            if row.get("kind") in COACH_KINDS]
