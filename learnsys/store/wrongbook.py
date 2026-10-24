"""错题本域：wrong_items 是唯一来源；复习状态与资料标题由别的模块贴上来。"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import sqlite3

from ._base import _LOCK, now
from .materials import _attach_material_titles
from .review import _attach_review_states, _next_review, save_review_state


# ---- 统一错题本 ----
# 唯一来源是 wrong_items；asks.starred 只是 v1 的历史快照，迁移后不再读写。

WRONG_SOURCES = ("ask", "quiz", "cet6", "manual")

_WRONG_COLUMNS = (
    "id, ts, source, source_id, question, answer, my_answer, tags, note, "
    "auto, review_stage, last_review, mastered, material_id"
)


_QUESTION_NOISE = re.compile(
    r"[\s，。！？；：、“”‘’（）【】《》〈〉「」『』…—～·]+", re.UNICODE)


def wrong_fingerprint(question: str) -> str:
    """题目指纹：去空白/中文标点、转小写后哈希。

    只清中文标点和空白，**保留 `+ - * / = < >` 等数学符号** —— 否则
    「a+b」和「a-b」会撞成同一道题。
    """
    text = str(question or "")
    # 去掉题号前缀：「【第1题】」「第 2 题.」—— 自动工具和手动补收的题面才不会因前缀分家。
    text = re.sub(r"^\s*【\s*第\s*\d+\s*题\s*】", "", text)
    text = re.sub(r"^\s*第?\s*\d+\s*[题.、:：]\s*", "", text)
    cleaned = _QUESTION_NOISE.sub("", text).lower()
    return hashlib.sha1((cleaned or text).encode("utf-8")).hexdigest()[:16]
def _wrong_dict(row) -> dict:
    item = {
        "id": int(row[0]), "ts": row[1] or "", "source": row[2] or "manual",
        "source_id": row[3] or "", "question": row[4] or "", "answer": row[5] or "",
        "my_answer": row[6] or "", "tags": row[7] or "", "note": row[8] or "",
        "auto": bool(row[9]), "review_stage": int(row[10] or 0),
        "last_review": row[11] or "", "mastered": bool(row[12]),
        "material_id": int(row[13] or 0), "material_title": "",
    }
    item["next_review"] = _next_review(item["ts"], item["last_review"],
                                       item["review_stage"])
    return item


def add_wrong_item(conn: sqlite3.Connection, *, question: str, answer: str = "",
                   my_answer: str = "", tags: str = "", note: str = "",
                   source: str = "manual", source_id: str | None = None,
                   auto: bool = False, material_id: int = 0) -> tuple[int, bool]:
    """收一道错题；返回 (id, 是否新建)。同 source+source_id 只留第一条。"""
    question = str(question or "").strip()
    if not question:
        raise ValueError("错题的问题不能为空")
    source = source if source in WRONG_SOURCES else "manual"
    source_id = (str(source_id).strip() or None) if source_id else None
    with _LOCK:
        cur = conn.execute(
            "INSERT OR IGNORE INTO wrong_items "
            "(ts, source, source_id, question, answer, my_answer, tags, note, "
            "auto, material_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), source, source_id, question, str(answer or ""),
             str(my_answer or ""), str(tags or ""), str(note or ""),
             1 if auto else 0, int(material_id or 0)))
        created = cur.rowcount > 0
        item_id = int(cur.lastrowid or 0) if created else 0
        if not created and source_id:
            row = conn.execute(
                "SELECT id FROM wrong_items WHERE source = ? AND source_id = ?",
                (source, source_id)).fetchone()
            item_id = int(row[0]) if row else 0
        conn.commit()
    return item_id, created


def toggle_ask_wrong(conn: sqlite3.Connection, ask_id: int) -> bool:
    """问答「收藏 / 取消收藏」= 收进 / 移出统一错题本；返回新状态。"""
    source_id = f"ask:{int(ask_id)}"
    with _LOCK:
        row = conn.execute(
            "SELECT id FROM wrong_items WHERE source = 'ask' AND source_id = ?",
            (source_id,)).fetchone()
        if row is not None:
            conn.execute("DELETE FROM wrong_items WHERE id = ?", (int(row[0]),))
            conn.commit()
            return False
        ask = conn.execute(
            "SELECT ts, question, answer FROM asks WHERE id = ?",
            (int(ask_id),)).fetchone()
        if ask is None:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO wrong_items "
            "(ts, source, source_id, question, answer, auto) "
            "VALUES (?, 'ask', ?, ?, ?, 0)",
            (ask[0] or now(), source_id, ask[1] or "", ask[2] or ""))
        conn.commit()
        return True
def toggle_star(conn: sqlite3.Connection, ask_id: int) -> bool:
    """旧名字保留给快捷栏；语义已改为「收进 / 移出错题本」。"""
    return toggle_ask_wrong(conn, ask_id)
def get_wrong_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    with _LOCK:
        row = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
    if row is None:
        return None
    item = _attach_review_states(conn, [_wrong_dict(row)])[0]
    return _attach_material_titles(conn, [item])[0]
def wrong_items(conn: sqlite3.Connection, *, status: str = "all",
                source: str = "", limit: int = 200, today=None,
                material_id: int = 0) -> list[dict]:
    """错题列表。status：due 待复习 / mastered 已掌握 / all 全部（含已掌握）。"""
    with _LOCK:
        rows = conn.execute(
            f"SELECT {_WRONG_COLUMNS} FROM wrong_items ORDER BY ts DESC, id DESC"
        ).fetchall()
    today = str(today or dt.date.today().isoformat())[:10]
    items = _attach_review_states(conn, [_wrong_dict(row) for row in rows])
    if source in WRONG_SOURCES:
        items = [item for item in items if item["source"] == source]
    if material_id:
        items = [item for item in items
                 if int(item.get("material_id") or 0) == int(material_id)]
    if status == "due":
        items = [item for item in items
                 if not item["mastered"] and item["next_review"]
                 and item["next_review"] <= today]
        items.sort(key=lambda item: item["next_review"])
    elif status == "mastered":
        items = [item for item in items if item["mastered"]]
    limit = max(1, min(int(limit or 200), 1000))
    return _attach_material_titles(conn, items[:limit])


def wrong_material_facets(conn: sqlite3.Connection) -> list[dict]:
    """错题本里有题的资料，用于「按资料筛选」。"""
    with _LOCK:
        rows = conn.execute(
            "SELECT w.material_id, COALESCE(m.title, ''), COUNT(*) "
            "FROM wrong_items w LEFT JOIN materials m ON m.id = w.material_id "
            "WHERE w.material_id > 0 GROUP BY w.material_id "
            "ORDER BY COUNT(*) DESC, w.material_id DESC").fetchall()
    return [{"material_id": int(row[0]), "title": row[1] or "资料",
             "count": int(row[2] or 0)} for row in rows]


def wrong_due_items(conn: sqlite3.Connection, today=None) -> list[dict]:
    """到复习期的错题（启动提醒和页面共用这一个口径）。"""
    return wrong_items(conn, status="due", limit=1000, today=today)


def wrong_counts(conn: sqlite3.Connection, today=None) -> dict:
    day = str(today or dt.date.today().isoformat())[:10]
    with _LOCK:
        total, mastered, new_today = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(mastered), 0), "
            "COALESCE(SUM(ts LIKE ?), 0) FROM wrong_items",
            (f"{day}%",)).fetchone()
    return {"all": int(total or 0), "mastered": int(mastered or 0),
            "due": len(wrong_due_items(conn)), "new_today": int(new_today or 0)}


def set_wrong_mastered(conn: sqlite3.Connection, item_id: int, mastered: bool) -> bool:
    """手动标记 / 取消掌握。取消后回到「新卡」，今天就能重新复习。"""
    with _LOCK:
        row = conn.execute(
            "SELECT review_stage FROM wrong_items WHERE id = ?",
            (int(item_id),)).fetchone()
        if row is None:
            return False
        if mastered:
            conn.execute("UPDATE wrong_items SET mastered = 1 WHERE id = ?",
                         (int(item_id),))
            conn.commit()
            return True
        conn.execute(
            "UPDATE wrong_items SET mastered = 0, review_stage = 0, last_review = ? "
            "WHERE id = ?", (dt.date.today().isoformat(), int(item_id)))
        conn.commit()
    save_review_state(
        conn, "wrong", int(item_id), state="new",
        due=dt.date.today().isoformat(), stability=1.0, difficulty=5.0,
        reps=0, lapses=0, last_review="", scheduled_days=0, elapsed_days=0)
    return True


def delete_wrong_item(conn: sqlite3.Connection, item_id: int) -> bool:
    with _LOCK:
        cur = conn.execute("DELETE FROM wrong_items WHERE id = ?", (int(item_id),))
        conn.execute(
            "DELETE FROM review_state WHERE item_type = 'wrong' AND item_id = ?",
            (int(item_id),))
        conn.commit()
        return bool(cur.rowcount)
def due_starred(conn: sqlite3.Connection, today) -> list[int]:
    """兼容旧名字：返回错题本条目 id（不是 ask id）。"""
    return [item["id"] for item in wrong_due_items(conn, today)]
