"""写作/翻译提升计划：每天最多一条提醒（唯一决策点）。

只回答一个问题：今天最该做的那一件写作/翻译的事是什么。

优先级：
1. 最近整篇还没写二稿 → 推二稿（改到对比刷新题值）；
2. 今天已经动过写作/翻译 → 不再提醒；
3. 近 30 天错误画像第一 → 推对应技能的一句一译；
4. 本周还没整篇 → 推限时整篇。

不碰听力、听写和普通复习：提醒多了等于没提醒。
"""
from __future__ import annotations

import datetime
import json
from urllib.parse import quote

from learnsys.services.train import plan as train_plan
from learnsys.services.train import stats as train_stats
from learnsys.services.train import submissions as service
from learnsys.train import content

KINDS = ("writing", "translation")
WHOLE_MODES = ("practice", "timed")
REWRITE_WINDOW_DAYS = 30
TAB = {"writing": "writing", "translation": "translation"}

# 错误画像 → 一句一译的技能名（技能名以 translation.json 的 skill 为准）。
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


def _has_rewrite(conn, submission_id: int) -> bool:
    """只有提交过的二稿才算完成；草稿还停在编辑器里，不能把提醒跳过。"""
    row = conn.execute(
        "SELECT 1 FROM train_submissions WHERE parent_id = ? AND mode = 'rewrite' "
        "AND status <> 'draft' LIMIT 1", (int(submission_id),)).fetchone()
    return row is not None


def _latest_without_rewrite(conn, day: str) -> dict | None:
    """最近 30 天里，第一条还没有二稿的整篇提交。"""
    rows = conn.execute(
        "SELECT id, kind, prompt_id, mode, band, band_json, created_at "
        "FROM train_submissions "
        "WHERE kind IN ('writing', 'translation') "
        "AND mode IN ('practice', 'timed') "
        "ORDER BY id DESC LIMIT 20").fetchall()
    floor = (datetime.date.fromisoformat(day)
             - datetime.timedelta(days=REWRITE_WINDOW_DAYS)).isoformat()
    for row in rows:
        created = str(row[6] or "")[:10]
        if created and created < floor:
            break
        if _has_rewrite(conn, int(row[0])):
            continue
        return {"id": int(row[0]), "kind": row[1], "prompt_id": row[2],
                "mode": row[3], "band": row[4], "band_json": row[5],
                "created_at": row[6]}
    return None


def _rewrite_action(row: dict) -> dict:
    kind = str(row.get("kind") or "writing")
    review = _review(row)
    task = str(review.get("rewrite_task") or "").strip()
    if not task:
        task = "；".join(str(x) for x in (review.get("priorities") or [])[:2])
    title = f"给《{_prompt_title(kind, row.get('prompt_id') or '')}》写二稿"
    return {
        "kind": "rewrite",
        "title": title,
        "detail": (task or "只改上次批改点名的 3 处，其余不动")[:80],
        "href": (f"#/cet6?tab={TAB.get(kind, 'writing')}"
                 f"&submission={row['id']}&rewrite=1"),
        "label": "写二稿",
        "reason": "上次整篇还没重写",
        "minutes": 30 if kind == "writing" else 10,
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
        "kind": "skill",
        "title": f"专项：{skill} 10 句",
        "detail": f"近 30 天「{kind}」错 {count} 次，是当前最大的扣分项",
        "href": "#/cet6?tab=translation&skill=" + quote(skill, safe=""),
        "label": "去练 10 句",
        "reason": f"错误画像：{kind}",
        "minutes": 10,
        "skill": skill,
    }


def _week_whole_count(conn, day: str) -> int:
    today = datetime.date.fromisoformat(day)
    monday = (today - datetime.timedelta(days=today.weekday())).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM train_submissions "
        "WHERE kind IN ('writing', 'translation') "
        "AND mode IN ('practice', 'timed') "
        "AND substr(created_at, 1, 10) >= ?", (monday,)).fetchone()
    return int(row[0] or 0)


def _whole_action(conn) -> dict:
    items = service.list_prompts(conn, "writing").get("items") or []
    fresh = next((item for item in items if not item.get("done")), None)
    fresh = fresh or (items[0] if items else {})
    detail = (f"{fresh.get('title') or '写作'} · "
              f"{fresh.get('minutes') or 30} 分钟 · 写完直接批改")
    return {
        "kind": "whole",
        "title": "本周还没写整篇",
        "detail": detail,
        "href": "#/cet6?tab=writing",
        "label": "开始整篇",
        "reason": "本周整篇数为 0",
        "minutes": 30,
    }


def candidates(conn, day: str = "") -> list[dict]:
    """今天可做的写作/翻译提升项，按优先级排序（不判断今天是否已经练过）。

    二稿 > 弱项技能 > 本周整篇；今日页拿它当「训练格」的备选池，
    `build()` 只取第一项，保证提醒与行动卡同一口径。
    """
    day = str(day or datetime.date.today().isoformat())[:10]
    rows: list[dict] = []
    whole = _latest_without_rewrite(conn, day)
    if whole:
        rows.append(_rewrite_action(whole))
    weak = _top_error(conn)
    if weak:
        rows.append(_skill_action(*weak))
    if _week_whole_count(conn, day) < 1:
        rows.append(_whole_action(conn))
    return rows


def build(conn, day: str = "") -> dict | None:
    """返回今天唯一一条写作/翻译提醒；没有就返回 None。"""
    day = str(day or datetime.date.today().isoformat())[:10]
    rows = candidates(conn, day)
    if not rows:
        return None
    # 二稿优先：即使今天已经练过，也先把上次的整篇收口。
    if rows[0].get("kind") == "rewrite":
        return rows[0]
    today = train_plan.today_activity(conn, day)
    if today.get("writing") or today.get("translation") or today.get("sentence"):
        return None
    return rows[0]
