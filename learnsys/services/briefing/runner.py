"""简报生成流水线 + 单 worker + 每日调度线程。"""
from __future__ import annotations

import datetime as dt
import os
import queue
import re
import sys
import threading

from learnsys import diagnostics, store
from learnsys.llm.config import load_config

from . import feed, pick
from . import summarize as summarizer
from .settings import briefing_settings
from .sources import CATEGORY_LABELS

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_QUEUE: queue.Queue = queue.Queue()
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_SCHEDULER: threading.Thread | None = None
_PENDING: set[str] = set()
_STOP = threading.Event()


def day_of(moment: dt.datetime | None = None) -> str:
    return (moment or dt.datetime.now()).strftime("%Y-%m-%d")


def _valid_day(day: str) -> str:
    text = str(day or "").strip()
    if not _DAY_RE.match(text):
        raise ValueError("日期要写成 YYYY-MM-DD")
    try:
        dt.datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期不存在") from exc
    return text


def _public(row: dict | None, *, day: str) -> dict:
    if not row:
        return {"day": day, "status": "missing", "items": []}
    items = []
    for item in row.get("items") or []:
        items.append({
            "id": item.get("id"), "category": item.get("category", "other"),
            "category_label": CATEGORY_LABELS.get(item.get("category"), "其他"),
            "title": item.get("title", ""), "title_zh": item.get("title_zh", ""),
            "summary": item.get("summary", ""), "url": item.get("url", ""),
            "source": item.get("source", ""),
            "published_at": item.get("published_at", ""),
            "rank": item.get("rank", 0), "read": bool(item.get("read")),
            "starred": bool(item.get("starred")),
            "summary_source": (item.get("meta") or {}).get("summary_source", ""),
        })
    stats = row.get("source_stats") or {}
    ok = sum(1 for value in stats.values()
             if isinstance(value, dict) and value.get("status") == "ok")
    return {
        "id": row.get("id"), "day": row.get("day", day),
        "status": row.get("status", "missing"), "title": row.get("title", ""),
        "intro": row.get("intro", ""), "item_count": int(row.get("item_count") or 0),
        "model": row.get("model", ""), "error": row.get("error", ""),
        "created_at": row.get("created_at", ""), "updated_at": row.get("updated_at", ""),
        "source_ok": ok, "source_total": len(stats), "items": items,
    }


def today(day: str = "") -> dict:
    day = _valid_day(day) if day else day_of()
    conn = store.connect()
    try:
        row = store.get_briefing_day(conn, day)
    finally:
        conn.close()
    if row:
        data = _public(row, day=day)
        settings = briefing_settings()
        data["generate_at"] = settings["generate_at"]
        data["enabled"] = settings["enabled"]
        return data
    settings = briefing_settings()
    status = "missing"
    if day == day_of() and not _due(dt.datetime.now(), settings["generate_at"]):
        status = "scheduled"
    return {"day": day, "status": status, "items": [],
            "generate_at": settings["generate_at"], "enabled": settings["enabled"]}


def get(day: str) -> dict:
    return today(day)


def days(limit: int = 30) -> list[dict]:
    conn = store.connect()
    try:
        return store.list_briefing_days(conn, limit=limit)
    finally:
        conn.close()


def update_item(item_id: int, *, read: bool | None = None,
                starred: bool | None = None) -> dict | None:
    conn = store.connect()
    try:
        item = store.update_briefing_item(conn, item_id, read=read, starred=starred)
    finally:
        conn.close()
    if not item:
        return None
    return {key: item[key] for key in
            ("id", "category", "title", "title_zh", "summary", "url", "source",
             "published_at", "rank", "read", "starred", "read_at")}


def mark_all_read(day: str) -> int:
    day = _valid_day(day)
    conn = store.connect()
    try:
        return store.read_all_briefing(conn, day)
    finally:
        conn.close()


def _fallback_rows(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        brief = str(item.get("summary") or "").strip()
        rows.append({"title_zh": "",
                     "summary": brief[:120] if brief else str(item.get("title") or ""),
                     "summary_source": "feed"})
    return rows


def generate(day: str, *, force: bool = False) -> dict:
    """同步生成当天简报；worker / 测试 / 命令行都走这里。"""
    day = _valid_day(day)
    conn = store.connect()
    briefing_id = 0
    try:
        briefing_id, _ = store.create_briefing_day(conn, day)
        claimed = store.claim_briefing(conn, day, force=force)
        if claimed is None:
            row = store.get_briefing_day(conn, day)
            return _public(row, day=day)

        items, stats = feed.fetch_all()
        if not items:
            store.finish_briefing(
                conn, briefing_id, status="failed", title=f"{day} 每日简报",
                source_stats=stats, error="所有信息源都没有取到条目", item_count=0)
            return _public(store.get_briefing_day(conn, day), day=day)

        seen = store.recent_briefing_seen(conn, days=3, before_day=day)
        chosen = pick.select(
            items,
            seen_url_keys={entry["url_key"] for entry in seen if entry["url_key"]},
            seen_titles=[entry["title"] for entry in seen if entry["title"]],
        )
        if not chosen:
            store.finish_briefing(
                conn, briefing_id, status="failed", title=f"{day} 每日简报",
                source_stats=stats, error="没有筛选出可用的条目", item_count=0)
            return _public(store.get_briefing_day(conn, day), day=day)

        # 英文源/短摘要的 feed 只给标题时补一段正文，摘要才有事实可写。
        try:
            feed.fetch_bodies(chosen)
        except Exception as exc:
            diagnostics.log_swallow("每日简报：补抓正文", exc)

        cfg = load_config()
        try:
            intro, rows, summary_error = summarizer.summarize(chosen, cfg=cfg)
        except Exception as exc:  # 单条摘要失败不能把整份简报丢掉
            intro, rows = "", _fallback_rows(chosen)
            summary_error = f"摘要失败，先用原文：{exc}"

        payload = []
        for item, row in zip(chosen, rows):
            meta = {
                "source_id": item.get("source_id", ""),
                "feed": (item.get("meta") or {}).get("feed", ""),
                "original_title": item.get("title", ""),
                "original_summary": item.get("summary", ""),
                "time_estimated": bool((item.get("meta") or {}).get("time_estimated")),
                "score": item.get("score", 0),
                "prompt_version": summarizer.PROMPT_VERSION,
                "summary_source": row.get("summary_source", "feed"),
            }
            payload.append({
                "category": item.get("category", "other"),
                "title": item.get("title", ""),
                "title_zh": row.get("title_zh", ""),
                "summary": row.get("summary", ""),
                "url": item.get("url", ""), "url_key": item.get("url_key", ""),
                "source": item.get("source_name", ""),
                "published_at": item.get("published_at", ""),
                "meta": meta,
            })
        store.save_briefing_items(conn, briefing_id, payload)

        failed_sources = [value.get("name", key) for key, value in stats.items()
                          if value.get("status") != "ok"]
        notes = []
        if failed_sources:
            notes.append(f"{len(failed_sources)} 个源暂不可用："
                         + "、".join(failed_sources[:3]))
        if summary_error:
            notes.append(summary_error)
        status = "partial" if notes else "ready"
        model = cfg.model_for("briefing") or cfg.fast_model or cfg.model
        store.finish_briefing(
            conn, briefing_id, status=status, title=f"{day} 每日简报",
            intro=intro, model=model, source_stats=stats,
            error="；".join(notes), item_count=len(payload))
        return _public(store.get_briefing_day(conn, day), day=day)
    except Exception as exc:
        if briefing_id:
            try:
                store.finish_briefing(
                    conn, briefing_id, status="failed", title=f"{day} 每日简报",
                    error=f"生成失败：{exc}")
            except Exception as exc2:
                diagnostics.log_swallow("每日简报：标记失败状态", exc2)
        raise
    finally:
        conn.close()


def submit(day: str = "", *, force: bool = False) -> dict:
    day = _valid_day(day) if day else day_of()
    ensure_started()
    with _LOCK:
        if day in _PENDING and not force:
            return {"day": day, "status": "pending", "queued": True}
        _PENDING.add(day)
    _QUEUE.put((day, bool(force)))
    return {"day": day, "status": "pending", "queued": True}


def _worker_loop() -> None:
    while not _STOP.is_set():
        try:
            day, force = _QUEUE.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            generate(day, force=force)
        except Exception as exc:
            diagnostics.log_swallow("每日简报：生成任务", exc)
        finally:
            with _LOCK:
                _PENDING.discard(day)
            _QUEUE.task_done()


def _due(moment: dt.datetime, generate_at: str) -> bool:
    try:
        hour, minute = (int(part) for part in str(generate_at).split(":", 1))
    except (TypeError, ValueError):
        hour, minute = 7, 30
    return (moment.hour, moment.minute) >= (hour, minute)


def scheduler_tick(now: dt.datetime | None = None) -> None:
    """一次调度检查；测试直接调它，不用等线程。"""
    settings = briefing_settings()
    if not settings["enabled"]:
        return
    now = now or dt.datetime.now()
    if not _due(now, settings["generate_at"]):
        return
    day = day_of(now)
    conn = store.connect()
    try:
        store.recover_stale_briefings(conn, minutes=10)
        row = store.get_briefing_day(conn, day)
    finally:
        conn.close()
    if row and row.get("status") in ("ready", "partial", "running"):
        return
    if row and row.get("status") == "failed":
        # 失败后至少隔 30 分钟再自动重试，避免每 5 分钟反复打网络；手动重试不受限。
        try:
            updated = dt.datetime.strptime(
                str(row.get("updated_at") or ""), "%Y-%m-%d %H:%M:%S")
            if (now - updated).total_seconds() < 1800:
                return
        except ValueError:
            pass
    submit(day)


def _scheduler_loop() -> None:
    if _STOP.wait(30):
        return
    while not _STOP.is_set():
        try:
            scheduler_tick()
        except Exception as exc:
            diagnostics.log_swallow("每日简报：调度检查", exc)
        if _STOP.wait(300):
            return


def _is_test_process() -> bool:
    return "unittest" in sys.modules or os.environ.get("LEARNSYS_DISABLE_BRIEFING") == "1"


def ensure_started() -> None:
    if _is_test_process():
        return
    global _WORKER, _SCHEDULER
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _STOP.clear()
            _WORKER = threading.Thread(
                target=_worker_loop, name="briefing-worker", daemon=True)
            _WORKER.start()
        if _SCHEDULER is None or not _SCHEDULER.is_alive():
            _SCHEDULER = threading.Thread(
                target=_scheduler_loop, name="briefing-scheduler", daemon=True)
            _SCHEDULER.start()


def shutdown() -> None:
    _STOP.set()
    for thread in (_SCHEDULER, _WORKER):
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
