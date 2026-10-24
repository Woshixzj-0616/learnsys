"""学习记录类读工具：问答/转写/快照检索、今日概览、挂载文档、截图 OCR。"""
from __future__ import annotations

import datetime
import pathlib

from learnsys import config, store
from learnsys.services import study
from .context import ToolContext, _one_line, _safe_path, _stamp


def search_records(query: str, days: int = 7, kinds: list | None = None,
                   limit: int = 8, *, data_root: pathlib.Path | None = None) -> str:
    """跨天搜问答 / 转写 / 快照文字；结果按时间倒序。"""
    query = str(query or "").strip()
    days = max(1, min(int(days or 7), 90))
    limit = max(1, min(int(limit or 8), 20))
    wanted = set(kinds or ["asks", "transcripts", "frames"])
    root = pathlib.Path(data_root or config.DATA_ROOT)
    since = datetime.date.today() - datetime.timedelta(days=days)
    since_ts = since.isoformat() + " 00:00:00"
    # 空关键词不是错误：模型常拿它来「看最近记录」。LIKE '%%' 就是全匹配。
    pattern = f"%{query}%" if query else "%"
    what = f"和「{query}」相关" if query else ""
    found: list[tuple[str, str, str]] = []      # (ts, 来源, 正文)

    for day, db_path in study.storage_dbs(root):
        if day < since:
            continue
        try:
            conn = store.connect(db_path)
        except Exception:
            continue
        try:
            if "asks" in wanted:
                for ts, question, answer in conn.execute(
                        "SELECT ts, question, answer FROM asks "
                        "WHERE (question LIKE ? OR answer LIKE ?) AND ts >= ? "
                        "ORDER BY ts DESC LIMIT ?", (pattern, pattern, since_ts, limit)):
                    found.append((_stamp(ts), "问答",
                                  f"问：{_one_line(question, 160)}｜答：{_one_line(answer, 260)}"))
            if "transcripts" in wanted:
                for ts, text in conn.execute(
                        "SELECT ts_start, text FROM transcripts "
                        "WHERE text LIKE ? AND ts_start >= ? "
                        "ORDER BY ts_start DESC LIMIT ?", (pattern, since_ts, limit)):
                    found.append((_stamp(ts), "课堂转写", _one_line(text, 320)))
            if "frames" in wanted:
                for ts, text in conn.execute(
                        "SELECT ts, text FROM frame_text "
                        "WHERE text LIKE ? AND ts >= ? "
                        "ORDER BY ts DESC LIMIT ?", (pattern, since_ts, limit)):
                    found.append((_stamp(ts), "屏幕文字", _one_line(text, 320)))
        except Exception:
            continue
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if len(found) >= limit * 3:
            break

    if not found:
        return f"最近 {days} 天里没有{what}的学习记录。"

    found.sort(key=lambda item: item[0], reverse=True)
    lines = [f"最近 {days} 天里{what}的记录（新→旧，最多 {limit} 条）："]
    total = 0
    for ts, source, body in found[:limit]:
        line = f"[{source} {ts}] {body}"
        if total + len(line) > 6000:
            break
        lines.append(line)
        total += len(line)
    lines.append("（以上来自本地记录，可能不完整；没有提到的内容不要当成不存在，也不要编造。）")
    return "\n".join(lines)


def today_summary(*, data_root: pathlib.Path | None = None) -> str:
    """今天的学习概况。"""
    root = pathlib.Path(data_root or config.DATA_ROOT)
    today = datetime.date.today()
    day_text = today.isoformat()
    unified = root / "learning.db"
    if unified.exists():
        db_path = unified
    else:
        # 兼容 v1：还没迁移时读按天库
        db_path = root / f"{today.year}.{today.month}.{today.day}" / "learnsys.db"
    if not db_path.exists():
        return "今天还没有学习记录（没开录制，也没有问答）。"
    try:
        conn = store.connect(db_path)
    except Exception as exc:
        return f"读今天的记录失败：{exc}"
    try:
        stats = store.focus_stats(conn, day=day_text)
        ask_rows = store.recent_asks(conn, limit=5, day=day_text)
        ask_count = conn.execute(
            "SELECT COUNT(*) FROM asks WHERE ts LIKE ?", (f"{day_text}%",)).fetchone()[0]
        transcript_count, char_count = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(text)), 0) FROM transcripts "
            "WHERE ts_start LIKE ?", (f"{day_text}%",)).fetchone()
        due = store.wrong_due_items(conn, today)
    except Exception as exc:
        return f"统计今天的记录失败：{exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass

    lines = [f"今天（{day_text}）的学习概况："]
    minutes = float(stats.get("分钟") or 0)
    lines.append(
        f"- 记录时长 {minutes:.0f} 分钟，切换窗口 {stats.get('切换', 0)} 次")
    apps = stats.get("程序") or []
    if apps:
        lines.append("- 最久停在：" + "、".join(
            f"{name} {mins:.0f} 分" for name, mins in apps[:3]))
    lines.append(f"- 问答 {int(ask_count)} 条（这里只列最近 5 条）")
    lines.append(f"- 课堂转写 {int(transcript_count)} 段 / {int(char_count)} 字")
    if due:
        lines.append(f"- 错题本有 {len(due)} 题到复习期了")
    for row in ask_rows:
        lines.append(f"  · [{_stamp(row[0])}] {_one_line(row[1], 100)}")
    return "\n".join(lines)


def read_attachment(offset: int = 0, *, ctx: ToolContext) -> str:
    """读挂载文档的一段。"""
    text = (ctx.attachment_text or "").strip()
    if not text:
        return "当前没有挂载文档。"
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    chunk = text[start:start + 4000]
    if not chunk:
        return f"文档已经读完了（共 {len(text)} 字）。"
    return (f"【文档：{ctx.attachment_name or '未命名'} · 第 {start}–{start + len(chunk)} 字 / "
            f"共 {len(text)} 字】\n{chunk}")


def ocr_image(path: str, *, ctx: ToolContext) -> str:
    """对数据目录里的图片做 OCR。"""
    safe = _safe_path(path, ctx.data_root)
    if safe is None:
        return "这个路径不在学习工作台的数据目录里，不能读。"
    if not safe.exists():
        return f"图片不存在：{safe.name}"
    try:
        from learnsys.services.ocr import ocr_image as _ocr
        text = _ocr(str(safe))
    except Exception as exc:
        return f"OCR 没成功：{exc}"
    if not text.strip():
        return "这张图里没有识别到文字。"
    return f"【OCR：{safe.name}】\n{text[:4000]}"
