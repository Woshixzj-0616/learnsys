"""错题 / Anki / 每日报告 / 笔记导出（纯文本拼装，不碰界面）。"""
from __future__ import annotations

import csv
import io
import pathlib

from .context import _TRANSCRIPT_CAP

_WRONG_SOURCE_LABEL = {
    "ask": "问答收藏", "quiz": "测验错题", "manual": "手动收录", "cet6": "六级断点",
}


def wrongbook_csv_text(items: list[dict]) -> str:
    """错题条目 → Anki 可导入的 CSV 文本（不含 BOM，调用方决定）。

    正面只放题目；背面把正确答案和解析拼起来，避免自测时被提示。
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["正面（问题）", "背面（答案）", "我的作答", "来源",
                     "资料", "知识点", "收录时间"])
    for item in items:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        note = str(item.get("note") or "").strip()
        if not question:
            continue
        if note and note not in answer:
            answer = (answer + "\n\n" + note).strip()
        writer.writerow([
            question, answer or "（还没有答案）",
            str(item.get("my_answer") or "").strip(),
            _WRONG_SOURCE_LABEL.get(str(item.get("source") or ""), "错题"),
            str(item.get("material_title") or "").strip(),
            str(item.get("tags") or "").strip(),
            str(item.get("ts") or "")[:16],
        ])
    return out.getvalue()


def export_wrongbook_csv(items: list[dict], path: pathlib.Path) -> int:
    """写 utf-8-sig（Excel 双击不乱码，Anki 也认）；返回写入条数。"""
    text = wrongbook_csv_text(items)
    pathlib.Path(path).write_text("﻿" + text, encoding="utf-8")
    # 用 csv 读回再数：答案里的换行在 CSV 里是同一行记录，不能按 splitlines 数。
    rows = list(csv.reader(io.StringIO(text)))
    return max(0, len(rows) - 1)


def export_anki_csv(rows, path: pathlib.Path) -> int:
    """旧调用壳：问答行 [(ts, q, a, kind, image, id), ...] → 统一错题 CSV。"""
    items = [
        {"question": row[1], "answer": row[2], "ts": row[0], "source": "ask"}
        for row in rows
    ]
    return export_wrongbook_csv(items, path)


def build_daily_report(day_name: str, summary_lines: list[str], asks: list,
                       transcript_text: str, starred: int, recordings: int,
                       ai_summary: str = "") -> str:
    """把一天的数据拼成 Markdown 报告。ai_summary 是 AI 总结那段（可能为空）。"""
    lines = [f"# 学习报告 · {day_name}", ""]
    if ai_summary:
        lines += ["## 要点", "", ai_summary, ""]
    lines += ["## 记录概览", ""]
    lines += (summary_lines or ["（今天没有开过录制）"])
    lines += ["", f"问答 {len(asks)} 条 ｜ 错题本新增 {starred} 条 ｜ 录像 {recordings} 段", ""]
    if asks:
        lines += ["## 今天问过的", ""]
        for row in asks:
            q = (row[1] or "").strip().replace("\n", " ")
            a = (row[2] or "").strip().replace("\n", " ")
            stamp = str(row[0])[11:16]
            lines.append(f"- **{stamp}** {q} —— {a[:120]}{'…' if len(a) > 120 else ''}")
        lines.append("")
    if transcript_text:
        lines += ["## 课堂转写", "", transcript_text[-_TRANSCRIPT_CAP:], ""]
    return "\n".join(lines)


def export_day_notes_md(asks: list, path: pathlib.Path, title: str) -> int:
    """问答行 → Markdown 笔记（一问一段）。返回写入条数。"""
    count = 0
    out = [f"# {title}", ""]
    for row in asks:
        q = (row[1] or "").strip()
        a = (row[2] or "").strip()
        if not q:
            continue
        stamp = str(row[0])[:16]
        kind = row[3] if len(row) > 3 else "text"
        tag = "【图问】" if kind == "image" else "【文问】"
        out += [f"## {stamp} {tag}{q}", "", a or "（无答案）", ""]
        count += 1
    pathlib.Path(path).write_text("\n".join(out), encoding="utf-8")
    return count
