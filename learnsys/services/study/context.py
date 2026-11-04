"""转写上下文、历史库定位、专注文案。

纯函数，不带 Qt；转写行形状兼容 3 列 / 4 列（见 `_transcript_ts_text`）。
"""
from __future__ import annotations

import datetime
import pathlib

_TRANSCRIPT_CAP = 4000          # 复盘时给 AI 的转写正文上限（字符）
_CONTEXT_CAP = 1200             # 追问时附带的转写上下文上限 —— 太长撑 token、也没那么相关
_CONTEXT_MINUTES = 12           # 追问只带最近这么多分钟的转写（不够就有多少带多少）


def day_dbs(data_root: pathlib.Path) -> list[tuple[datetime.date, pathlib.Path]]:
    """数据根目录下所有「有库的日子」，新→旧。名字是 2026.10.6 这种 ⇒ 按日期解析排序，别按字符串。"""
    out: list[tuple[datetime.date, pathlib.Path]] = []
    if not data_root.is_dir():
        return out
    for db in data_root.glob("*/learnsys.db"):
        parts = db.parent.name.split(".")
        try:
            day = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            continue
        out.append((day, db))
    out.sort(key=lambda pair: pair[0], reverse=True)
    return out


def storage_dbs(data_root: pathlib.Path) -> list[tuple[datetime.date, pathlib.Path]]:
    """当前该读哪个库：v2 统一库存在就只读它；否则退回旧按天库。

    迁移后旧按天库仍在（只读备份），再一起扫会把同一条问答数两遍。
    """
    unified = data_root / "learning.db"
    if unified.exists():
        return [(datetime.date.today(), unified)]
    return day_dbs(data_root)


def _transcript_ts_text(row) -> tuple[str, str]:
    """转写行的时间/正文，兼容两种形状：search_transcripts 的 4 列（含 session_id）
    和测试/手工传的 3 列 —— 4 列时正文在 [3]，3 列时在 [2]（真踩过：拿 [2] 当正文，
    摘要全是 ts_end，AI 看到「转写是空的」）。"""
    if len(row) >= 4:
        return str(row[1]), (row[3] or "").strip()
    return str(row[0]), (row[2] or "").strip()


def transcripts_digest(rows) -> str:
    """转写行 → 一段可读正文（带时刻，去空行）。"""
    pieces = []
    for row in rows:
        ts, text = _transcript_ts_text(row)
        if text:
            pieces.append(f"[{ts[11:16] if len(ts) >= 16 else ts}] {text}")
    return "\n".join(pieces)


def transcript_context(rows, now: datetime.datetime | None = None) -> str:
    """追问要附带的课上上下文：最近 `_CONTEXT_MINUTES` 分钟的转写，超长截尾。

    rows 时间升序，形状兼容 3 列 / 4 列（见 _transcript_ts_text）。没有就回空串。
    """
    if not rows:
        return ""
    now = now or datetime.datetime.now()
    floor = now.timestamp() - _CONTEXT_MINUTES * 60
    pieces = []
    for row in rows:
        ts, text = _transcript_ts_text(row)
        try:
            moment = datetime.datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if moment.timestamp() >= floor and text:
            pieces.append(text)
    if not pieces:
        return ""
    return "（以下是刚录到的课堂转写片段，供参考回答本题）：" + "\n".join(pieces)[-_CONTEXT_CAP:]


def focus_line(stats: dict) -> str:
    """专注统计 → 一句给人看的文案。"""
    minutes = float(stats.get("分钟") or 0)
    line = f"今天记录了 {minutes:.0f} 分钟（{minutes / 60:.1f} 小时），切了 {stats.get('切换', 0)} 次窗口"
    apps = stats.get("程序") or []
    if apps:
        pretty = "、".join(f"{name} {mins:.0f} 分" for name, mins in apps[:3])
        line += f"。最久停在：{pretty}"
    return line
