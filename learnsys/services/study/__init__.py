"""学习功能门面：复盘拼题 / 转写上下文 / 专注文案 / 导出 / 文档解析。

**不带 Qt** —— 全是「给数据、回数据」的东西，测试不用起界面。
实现按职责拆在四个子模块；调用方继续用 `services.study.xxx`，新逻辑别往本门面加：

- `study_quiz`     复盘 / 测验 / 术语表提示词（口径唯一落点）
- `study_context`  转写上下文、历史库定位、专注文案
- `study_export`   错题 / Anki / 每日报告 / 笔记导出
- `study_document` PDF / DOCX / PPTX / TXT / MD 解析
"""
from __future__ import annotations

from .context import (
    _CONTEXT_CAP, _CONTEXT_MINUTES, _TRANSCRIPT_CAP, _transcript_ts_text,
    day_dbs, focus_line, storage_dbs, transcript_context, transcripts_digest,
)
from .document import extract_doc_text, extract_document
from .export import (
    _WRONG_SOURCE_LABEL, build_daily_report, export_anki_csv,
    export_day_notes_md, export_wrongbook_csv, wrongbook_csv_text,
)
from .quiz import (
    REVIEW_DISPLAY, _mastery_pct, _paged_preview, _weak_focus_block,
    build_glossary_question, build_material_quiz_question, build_quiz_question,
    build_review_question,
)

__all__ = [
    "REVIEW_DISPLAY",
    "build_daily_report", "build_glossary_question",
    "build_material_quiz_question", "build_quiz_question", "build_review_question",
    "day_dbs", "export_anki_csv", "export_day_notes_md", "export_wrongbook_csv",
    "extract_doc_text", "extract_document", "focus_line", "storage_dbs",
    "transcript_context", "transcripts_digest", "wrongbook_csv_text",
]
