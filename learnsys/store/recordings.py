"""录像域（P23）：会话上的视频字段、录像列表、转写读取与清理。

一段录像就是一条 `sessions` 行；视频原件、缩略图、幻灯片目录都记在这一行上。
转写继续用 `transcripts`，按 `session_id` 聚合；视频是唯一原件。
"""
from __future__ import annotations

import datetime as dt
import pathlib
import shutil
import sqlite3

from learnsys import config
from ._base import _LOCK


def default_title(started_at: str) -> str:
    """`2026-10-25 14:03:12` → `10-25 14:03 录像`。"""
    try:
        moment = dt.datetime.strptime(str(started_at)[:19], "%Y-%m-%d %H:%M:%S")
        return f"{moment:%m-%d %H:%M} 录像"
    except Exception:
        return "录像"


def update_video(conn: sqlite3.Connection, session_id: int, *,
                 title: str = "", video_path: str = "", video_bytes: int = 0,
                 duration_ms: int = 0, thumb_path: str = "",
                 slides_dir: str = "") -> None:
    with _LOCK:
        conn.execute(
            "UPDATE sessions SET title = ?, video_path = ?, video_bytes = ?, "
            "duration_ms = ?, thumb_path = ?, slides_dir = ? WHERE id = ?",
            (str(title or ""), str(video_path or ""), int(video_bytes or 0),
             int(duration_ms or 0), str(thumb_path or ""),
             str(slides_dir or ""), int(session_id)))
        conn.commit()


def set_material(conn: sqlite3.Connection, session_id: int, material_id: int) -> None:
    with _LOCK:
        conn.execute("UPDATE sessions SET material_id = ? WHERE id = ?",
                     (int(material_id or 0), int(session_id)))
        conn.commit()


def set_analysis(conn: sqlite3.Connection, session_id: int, result_id: int) -> None:
    with _LOCK:
        conn.execute("UPDATE sessions SET analysis_result_id = ? WHERE id = ?",
                     (int(result_id or 0), int(session_id)))
        conn.commit()


def _row(conn: sqlite3.Connection, session_id: int):
    return conn.execute(
        "SELECT id, started_at, COALESCE(ended_at, ''), kind, title, video_path, "
        "video_bytes, duration_ms, thumb_path, slides_dir, material_id, "
        "analysis_result_id FROM sessions WHERE id = ?", (int(session_id),)).fetchone()


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _offset(started_at: str, stamp: str) -> float:
    try:
        start = dt.datetime.strptime(str(started_at)[:19], "%Y-%m-%d %H:%M:%S")
        moment = dt.datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
        return max(0.0, (moment - start).total_seconds())
    except Exception:
        return 0.0


def transcript_text(conn: sqlite3.Connection, session_id: int,
                    cap: int = 12000) -> str:
    """录像转写 → 可读正文（带视频内时刻）；超长截前 cap 字并注明。"""
    row = _row(conn, session_id)
    if row is None:
        return ""
    started_at = row[1]
    rows = conn.execute(
        "SELECT ts_start, text FROM transcripts WHERE session_id = ? "
        "ORDER BY ts_start, id", (int(session_id),)).fetchall()
    pieces = []
    for ts_start, text in rows:
        text = str(text or "").strip()
        if text:
            pieces.append(f"[{_clock(_offset(started_at, ts_start))}] {text}")
    joined = "\n".join(pieces)
    if len(joined) > cap:
        return joined[:cap].rstrip() + f"\n（后面还有 {len(joined) - cap} 字，已省略）"
    return joined


def _slides(slides_dir: str, session_id: int,
            ocr_map: dict | None = None) -> list[dict]:
    if not slides_dir:
        return []
    folder = pathlib.Path(slides_dir)
    try:
        files = sorted(folder.glob("*.jpg"))
    except OSError:
        return []
    ocr_map = ocr_map or {}
    return [{"name": item.name, "path": str(item),
             "url": f"/media/recordings/{int(session_id)}/slides/{item.name}",
             "text": ocr_map.get(str(item), "")}
            for item in files]


def _slide_stamp(started_at: str, name: str) -> str:
    """`slide_0001_140312.jpg` + 会话日期 → `2026-10-25 14:03:12`。"""
    try:
        clock = pathlib.Path(name).stem.rsplit("_", 1)[-1]
        if len(clock) == 6 and clock.isdigit():
            return f"{str(started_at)[:10]} {clock[:2]}:{clock[2:4]}:{clock[4:]}"
    except Exception:
        pass
    return str(started_at)


def recording_slides(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """这段录像的幻灯片 + OCR 文字（分析任务用；没有 OCR 的 text 为空）。"""
    row = _row(conn, session_id)
    if row is None:
        return []
    slides_dir, started_at = row[9], row[1]
    rows = conn.execute(
        "SELECT path, ts, text FROM frame_text WHERE session_id = ? "
        "ORDER BY ts, path", (int(session_id),)).fetchall()
    ocr = {str(path): {"ts": ts, "text": str(text or "")}
           for path, ts, text in rows}
    items = []
    for slide in _slides(slides_dir, session_id, {k: v["text"] for k, v in ocr.items()}):
        extra = ocr.get(slide["path"]) or {}
        slide["ts"] = extra.get("ts") or _slide_stamp(started_at, slide["name"])
        items.append(slide)
    return items


def get_recording(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = _row(conn, session_id)
    if row is None:
        return None
    (sid, started_at, ended_at, kind, title, video_path, video_bytes,
     duration_ms, thumb_path, slides_dir, material_id, analysis_result_id) = row
    rows = conn.execute(
        "SELECT ts_start, ts_end, text FROM transcripts WHERE session_id = ? "
        "ORDER BY ts_start, id", (int(sid),)).fetchall()
    items = []
    for ts_start, ts_end, text in rows:
        at = _offset(started_at, ts_start)
        items.append({
            "at": round(at, 1),
            "clock": _clock(at),
            "ts_start": ts_start,
            "ts_end": ts_end,
            "text": text,
        })
    ocr_rows = conn.execute(
        "SELECT path, text FROM frame_text WHERE session_id = ?",
        (int(sid),)).fetchall()
    ocr_map = {str(path): str(text or "") for path, text in ocr_rows}
    exists = bool(video_path) and pathlib.Path(video_path).is_file()
    return {
        "id": int(sid),
        "started_at": started_at,
        "ended_at": ended_at,
        "kind": kind,
        "title": title or default_title(started_at),
        "video_path": video_path,
        "video_exists": exists,
        "video_url": f"/media/recordings/{int(sid)}/video.mp4" if exists else "",
        "video_bytes": int(video_bytes or 0),
        "duration": round(int(duration_ms or 0) / 1000.0, 1),
        "thumb_path": thumb_path,
        "thumb_url": (f"/media/recordings/{int(sid)}/thumb.jpg"
                      if thumb_path and pathlib.Path(thumb_path).is_file() else ""),
        "slides_dir": slides_dir,
        "slides": _slides(slides_dir, int(sid), ocr_map),
        "ocr_chars": sum(len(text) for text in ocr_map.values()),
        "material_id": int(material_id or 0),
        "analysis_result_id": int(analysis_result_id or 0),
        "transcripts": items,
        "chars": sum(len(str(item["text"] or "")) for item in items),
    }


def list_recordings(conn: sqlite3.Connection, *, query: str = "",
                    limit: int = 50) -> list[dict]:
    query = str(query or "").strip()
    limit = max(1, min(int(limit or 50), 200))
    sql = (
        "SELECT s.id, s.started_at, COALESCE(s.ended_at, ''), s.title, "
        "s.video_path, s.video_bytes, s.duration_ms, s.thumb_path, s.slides_dir, "
        "(SELECT COUNT(*) FROM transcripts t WHERE t.session_id = s.id), "
        "(SELECT COALESCE(SUM(LENGTH(t.text)), 0) FROM transcripts t "
        " WHERE t.session_id = s.id), "
        "(SELECT t.text FROM transcripts t WHERE t.session_id = s.id "
        " ORDER BY t.ts_start, t.id LIMIT 1) "
        "FROM sessions s WHERE s.video_path <> ''")
    params: list = []
    if query:
        sql += (" AND EXISTS (SELECT 1 FROM transcripts t "
                "WHERE t.session_id = s.id AND t.text LIKE ?)")
        params.append(f"%{query}%")
    sql += " ORDER BY s.started_at DESC, s.id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    items = []
    for (sid, started_at, ended_at, title, video_path, video_bytes, duration_ms,
         thumb_path, slides_dir, count, chars, preview) in rows:
        items.append({
            "id": int(sid),
            "started_at": started_at,
            "ended_at": ended_at,
            "title": title or default_title(started_at),
            "video_exists": bool(video_path) and pathlib.Path(video_path).is_file(),
            "video_bytes": int(video_bytes or 0),
            "duration": round(int(duration_ms or 0) / 1000.0, 1),
            "thumb_url": (f"/media/recordings/{int(sid)}/thumb.jpg"
                          if thumb_path and pathlib.Path(thumb_path).is_file() else ""),
            "slides_dir": slides_dir,
            "transcripts": int(count or 0),
            "chars": int(chars or 0),
            "preview": " ".join(str(preview or "").split())[:80],
        })
    return items


def _under_video_root(path: pathlib.Path) -> bool:
    try:
        root = config.VIDEO_DIR.resolve()
        target = path.resolve()
        return target != root and target.is_relative_to(root)
    except Exception:
        return False


def delete_recording(conn: sqlite3.Connection, session_id: int, *,
                     remove_files: bool = True) -> dict:
    row = _row(conn, session_id)
    if row is None:
        return {"ok": False, "error": "没有这段录像"}
    video_path, slides_dir = row[5], row[9]
    folder = ""
    for candidate in (video_path, slides_dir):
        if candidate:
            folder = str(pathlib.Path(candidate).parent)
            break
    with _LOCK:
        conn.execute("DELETE FROM transcripts WHERE session_id = ?", (int(session_id),))
        conn.execute("DELETE FROM window_events WHERE session_id = ?", (int(session_id),))
        conn.execute("DELETE FROM frame_text WHERE session_id = ?", (int(session_id),))
        conn.execute("DELETE FROM sessions WHERE id = ?", (int(session_id),))
        conn.commit()
    removed = False
    if remove_files and folder and _under_video_root(pathlib.Path(folder)):
        try:
            shutil.rmtree(folder)
            removed = True
        except OSError:
            removed = False
    return {"ok": True, "removed_files": removed, "folder": folder}


def recording_totals(conn: sqlite3.Connection, *, day: str = "") -> dict:
    """今日页/统计用：录像段数与总时长。"""
    where = "WHERE video_path <> ''"
    params: list = []
    if day:
        where += " AND started_at LIKE ?"
        params.append(f"{day}%")
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(duration_ms), 0), "
        f"COALESCE(SUM(video_bytes), 0) FROM sessions {where}", params).fetchone()
    return {"count": int(row[0] or 0), "seconds": round(int(row[1] or 0) / 1000.0, 1),
            "bytes": int(row[2] or 0)}
