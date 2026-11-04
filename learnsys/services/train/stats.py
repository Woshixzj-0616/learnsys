"""六级训练统计：档位趋势、错误画像、训练量（只读，不写任何学习数据）。

口径：
- 只统计 `train_submissions.status='reviewed'`；
- 一句一译只计次数与错误类型，不参与档位/词数/信息点统计；
- 错误类型来自批改 JSON 的 `errors[].type`（单句是 `must_fix[].type`），
  模型给的是自由文本，这里按原样聚合、不做同义词合并。
"""
from __future__ import annotations

import datetime
import json
from collections import Counter

from learnsys import store

KINDS = ("writing", "translation")
MAX_TREND_DAYS = 30
MAX_ERROR_TYPES = 12


def _review(row: dict) -> dict:
    try:
        data = json.loads(row.get("band_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _errors(row: dict, review: dict) -> list[dict]:
    raw = review.get("must_fix") if row.get("mode") == "sentence" else review.get("errors")
    return [item for item in raw or [] if isinstance(item, dict)]


def _blank() -> dict:
    return {"submissions": 0, "sentences": 0, "minutes": 0.0, "words": 0,
            "serious": 0, "errors": 0, "bands": [],
            "info_covered": 0, "info_total": 0}


def _finish(stats: dict) -> dict:
    bands = [band for band in stats.pop("bands") if band is not None]
    words = stats.pop("words")
    stats["minutes"] = round(stats["minutes"], 1)
    stats["avg_band"] = round(sum(bands) / len(bands), 1) if bands else None
    stats["last_band"] = bands[-1] if bands else None
    stats["best_band"] = max(bands) if bands else None
    stats["serious_per_100_words"] = (
        round(stats["serious"] * 100.0 / words, 2) if words else 0.0)
    stats["info_rate"] = (
        round(stats["info_covered"] * 100.0 / stats["info_total"], 1)
        if stats["info_total"] else None)
    return stats


def stats(conn, days: int = 30) -> dict:
    days = max(7, min(int(days or 30), 365))
    since = (datetime.date.today()
             - datetime.timedelta(days=days - 1)).isoformat()
    rows = store.reviewed_rows(conn, since=since)
    by_kind = {kind: _blank() for kind in KINDS}
    trend: dict[str, dict] = {}
    error_types: Counter = Counter()
    serious_types: Counter = Counter()

    for row in rows:
        kind = row.get("kind") if row.get("kind") in KINDS else "translation"
        stats_row = by_kind[kind]
        review = _review(row)
        is_sentence = row.get("mode") == "sentence"
        if is_sentence:
            stats_row["sentences"] += 1
        else:
            stats_row["submissions"] += 1
            stats_row["words"] += int(row.get("word_count") or 0)
            stats_row["serious"] += int(row.get("serious_count") or 0)
            stats_row["errors"] += int(row.get("error_count") or 0)
            stats_row["minutes"] += float(row.get("duration_s") or 0) / 60.0
            band = row.get("band")
            if band is not None:
                stats_row["bands"].append(int(band))
                day = str(row.get("updated_at") or row.get("created_at") or "")[:10]
                if day:
                    slot = trend.setdefault(day, {})
                    slot.setdefault(kind, []).append(int(band))
            if kind == "translation":
                points = review.get("info_points") or {}
                covered, total = points.get("covered"), points.get("total")
                if covered is not None and int(total or 0) > 0:
                    stats_row["info_covered"] += int(covered)
                    stats_row["info_total"] += int(total)
        for item in _errors(row, review):
            error_type = str(item.get("type") or "未分类").strip() or "未分类"
            error_types[error_type] += 1
            if item.get("severity") == "严重":
                serious_types[error_type] += 1

    for kind in KINDS:
        by_kind[kind] = _finish(by_kind[kind])

    trend_rows = []
    for day in sorted(trend)[-MAX_TREND_DAYS:]:
        entry = {"date": day}
        for kind in KINDS:
            values = trend[day].get(kind) or []
            entry[kind] = (round(sum(values) / len(values), 1)
                           if values else None)
        trend_rows.append(entry)

    return {
        "range": {"days": days, "since": since},
        "totals": {
            "submissions": sum(by_kind[kind]["submissions"] for kind in KINDS),
            "sentences": sum(by_kind[kind]["sentences"] for kind in KINDS),
            "minutes": round(sum(by_kind[kind]["minutes"] for kind in KINDS), 1),
            "errors": sum(by_kind[kind]["errors"] for kind in KINDS),
            "serious": sum(by_kind[kind]["serious"] for kind in KINDS),
        },
        "by_kind": by_kind,
        "band_trend": trend_rows,
        "error_types": [
            {"type": name, "count": count, "serious": serious_types.get(name, 0)}
            for name, count in error_types.most_common(MAX_ERROR_TYPES)
        ],
        "info_points": {
            "covered": sum(by_kind[kind]["info_covered"] for kind in KINDS),
            "total": sum(by_kind[kind]["info_total"] for kind in KINDS),
            "rate": (round(
                sum(by_kind[kind]["info_covered"] for kind in KINDS) * 100.0
                / sum(by_kind[kind]["info_total"] for kind in KINDS), 1)
                if sum(by_kind[kind]["info_total"] for kind in KINDS) else None),
        },
    }
