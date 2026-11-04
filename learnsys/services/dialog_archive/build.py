"""一次性构建并封存对话总汇。

约束：
- 目标文件已存在且 `status: sealed` 时不再写；只有 `new_archive=True`
  才另起一份新档案，旧文件永不覆盖、不追加。
- 正文先写临时文件，算完哈希再原子替换；落盘后设只读。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import pathlib
import re
import time

from learnsys.core.textkey import content_key

from . import render
from .redact import redact_text
from .sources import SOURCES

ARCHIVE_DIR = "记忆档案"


def _now_iso() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _day() -> str:
    return dt.datetime.now().strftime("%Y%m%d")


def _dedupe(sessions):
    merged: dict[tuple[str, str], object] = {}
    for session in sessions:
        key = (session.source, session.session_id)
        if key not in merged:
            merged[key] = session
            continue
        keep = merged[key]
        seen = {(m.role, content_key(m.text)) for m in keep.messages}
        for message in session.messages:
            mark = (message.role, content_key(message.text))
            if mark not in seen:
                keep.messages.append(message)
                seen.add(mark)
    return list(merged.values())


def _redact(sessions) -> dict[str, int]:
    total: dict[str, int] = {}
    for session in sessions:
        kept = []
        seen = set()
        for message in session.messages:
            text, counts = redact_text(message.text)
            for key, value in counts.items():
                total[key] = total.get(key, 0) + value
            mark = (message.role, content_key(text))
            if mark in seen:
                continue
            seen.add(mark)
            message.text = text
            kept.append(message)
        session.messages = kept
    return total


def _archive_name(data_root, new_archive: bool) -> tuple[str, pathlib.Path]:
    folder = pathlib.Path(data_root) / ARCHIVE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    base = f"对话总汇-{dt.datetime.now().strftime('%Y-%m-%d')}"
    path = folder / f"{base}.md"
    if not path.exists() or not new_archive:
        return f"dlg-{_day()}-01", path
    number = 2
    while True:
        path = folder / f"{base}-{number:02d}.md"
        if not path.exists():
            return f"dlg-{_day()}-{number:02d}", path
        number += 1


def _sealed(path: pathlib.Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    return "status: sealed" in head


def build_archive(data_root, *, cutoff_ts: float | None = None,
                  new_archive: bool = False) -> dict:
    cutoff_ts = time.time() if cutoff_ts is None else float(cutoff_ts)
    archive_id, path = _archive_name(data_root, new_archive)
    if path.exists() and _sealed(path) and not new_archive:
        return {"ok": True, "already_sealed": True, "path": str(path),
                "archive_id": archive_id}

    ordered: list[tuple[str, str, list]] = []
    stats: list[dict] = []
    missing: list[str] = []
    all_sessions = []
    all_errors = 0
    all_skipped = 0
    for source in SOURCES:
        try:
            result = source.collect(cutoff_ts)
        except Exception as exc:  # 单来源失败不影响其它来源
            result = {"files": 0, "sessions": [], "skipped": 0,
                      "errors": 1, "missing": f"收集失败：{exc}"}
        sessions = _dedupe(result.get("sessions") or [])
        sessions.sort(key=lambda item: (item.at or "", item.session_id))
        all_errors += int(result.get("errors") or 0)
        all_skipped += int(result.get("skipped") or 0)
        all_sessions.extend(sessions)
        reason = str(result.get("missing") or "")
        if reason:
            missing.append(reason)
        sections = [(source.section, source.label, sessions)] if sessions else []
        ordered.append((source.id, source.label, sections))
        st = {
            "id": source.id, "label": source.label,
            "status": "missing" if reason and not sessions else "imported",
            "files": int(result.get("files") or 0),
            "sessions": len(sessions),
            "messages": sum(len(item.messages) for item in sessions),
            "chars": sum(len(m.text) for item in sessions for m in item.messages),
            "errors": int(result.get("errors") or 0),
            "note": reason or source.missing_reason,
        }
        stats.append(st)

    redaction = _redact(all_sessions)
    body, rows = render.render_body(archive_id, ordered)
    body_bytes = body.encode("utf-8")
    # 校验从 BODY_START 起算，构建哈希也把哨兵一起算进去，避免差两个换行。
    hashed = (render.BODY_START + "\n\n" + body).encode("utf-8")
    body_sha = hashlib.sha256(hashed).hexdigest()
    created_at = _now_iso()
    cutoff_at = dt.datetime.fromtimestamp(cutoff_ts).strftime("%Y-%m-%dT%H:%M:%S")
    total_messages = sum(len(item.messages) for item in all_sessions)
    header = render.render_header(
        archive_id, created_at, cutoff_at, body_sha, len(hashed),
        len(body), stats, len(all_sessions), total_messages, redaction,
        rows, missing)
    full = header + "\n" + body
    file_sha = hashlib.sha256(full.encode("utf-8")).hexdigest()

    temp = path.with_suffix(".tmp")
    temp.write_text(full, encoding="utf-8", newline="\n")
    os.replace(temp, path)
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass
    path.with_suffix(path.suffix + ".sha256").write_text(
        file_sha + "  " + path.name + "\n", encoding="utf-8")

    return {
        "ok": True, "already_sealed": False, "path": str(path),
        "archive_id": archive_id, "file_sha256": file_sha,
        "body_sha256": body_sha, "body_bytes": len(body_bytes),
        "sessions": len(all_sessions), "messages": total_messages,
        "errors": all_errors, "skipped": all_skipped,
        "redaction": redaction, "sources": stats, "missing": missing,
    }


_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def verify_archive(path) -> dict:
    path = pathlib.Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    match = _FRONT.match(text)
    if not match:
        return {"ok": False, "reason": "缺少头部元数据"}
    head = match.group(1)
    marker = text.find(render.BODY_START)
    if marker < 0:
        return {"ok": False, "reason": "缺少 BODY START"}
    body = text[marker:]
    actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
    expected = re.search(r'body_sha256:\s*"([0-9a-f]+)"', head)
    if not expected or expected.group(1) != actual:
        return {"ok": False, "reason": "正文哈希不一致",
                "expected": expected.group(1) if expected else "",
                "actual": actual}
    last = text.rstrip().splitlines()[-1] if text.strip() else ""
    if last.strip() != render.BODY_END:
        return {"ok": False, "reason": "末尾哨兵不在最后一行"}
    message_count = re.search(r"message_count:\s*(\d+)", head)
    anchors = re.findall(r"<!-- learnsys:anchor archive:[^ ]+/m\d{4} -->", text)
    if message_count and len(anchors) != int(message_count.group(1)):
        return {"ok": False, "reason": "消息锚点数与 message_count 不一致",
                "anchors": len(anchors), "message_count": message_count.group(1)}
    if "status: sealed" not in head:
        return {"ok": False, "reason": "状态不是 sealed"}
    return {"ok": True, "body_sha256": actual,
            "message_count": int(message_count.group(1)) if message_count else 0,
            "size": path.stat().st_size}
