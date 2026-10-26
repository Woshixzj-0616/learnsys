"""Agent 工具层。

按用途拆成 schema / 各域工具 / 分发器；对外仍从 `learnsys.agent.tools` 导入。
"""
from __future__ import annotations

from .context import ToolContext, _one_line, _safe_path, _stamp
from .execute import execute
from .files import (STUDY_FILE_SUFFIXES, _study_target, run_code, write_study_file)
from .materials import read_material, save_material_note, search_materials
from .records import ocr_image, read_attachment, search_records, today_summary
from .schemas import (BROWSER_HISTORY_SCHEMA, BROWSER_STATUS_SCHEMA, CONFIRM_TOOLS,
                      DUE_REVIEWS_SCHEMA, FORGET_MEMORY_SCHEMA,
                      GET_CET6_CONTEXT_SCHEMA, GET_MASTERY_SCHEMA,
                      GET_TRAIN_SUMMARY_SCHEMA, LAUNCH_APP_SCHEMA,
                      LIST_RECORDINGS_SCHEMA, MAKE_PLAN_SCHEMA, OPEN_FILE_SCHEMA,
                      OPEN_URL_SCHEMA, RECENT_WRONG_ITEMS_SCHEMA, RUN_CODE_SCHEMA,
                      SAVE_MATERIAL_NOTE_SCHEMA, SAVE_MEMORY_SCHEMA,
                      SAVE_WRONGBOOK_SCHEMA, TOOL_SCHEMAS, WRITE_LABELS, WRITE_TOOLS,
                      WRITE_STUDY_FILE_SCHEMA, schemas_for, write_summary)
from .study_tools import (due_reviews, forget_memory, get_cet6_context,
                          get_mastery, get_train_summary, list_recordings,
                          recent_wrong_items, save_memory, save_wrongbook)
from .system_tools import (browser_history, browser_status, launch_app, open_file,
                           open_url)

__all__ = [
    "ToolContext", "execute", "schemas_for", "write_summary",
    "TOOL_SCHEMAS", "CONFIRM_TOOLS", "WRITE_TOOLS", "WRITE_LABELS",
    "MAKE_PLAN_SCHEMA", "RECENT_WRONG_ITEMS_SCHEMA", "GET_CET6_CONTEXT_SCHEMA",
    "DUE_REVIEWS_SCHEMA", "GET_MASTERY_SCHEMA", "GET_TRAIN_SUMMARY_SCHEMA",
    "LIST_RECORDINGS_SCHEMA",
    "OPEN_FILE_SCHEMA", "LAUNCH_APP_SCHEMA", "OPEN_URL_SCHEMA",
    "BROWSER_STATUS_SCHEMA", "BROWSER_HISTORY_SCHEMA",
    "SAVE_WRONGBOOK_SCHEMA", "SAVE_MEMORY_SCHEMA", "FORGET_MEMORY_SCHEMA",
    "SAVE_MATERIAL_NOTE_SCHEMA", "WRITE_STUDY_FILE_SCHEMA", "RUN_CODE_SCHEMA",
    "search_records", "today_summary", "read_attachment", "ocr_image",
    "search_materials", "read_material", "save_material_note",
    "save_wrongbook", "get_cet6_context", "save_memory", "forget_memory",
    "recent_wrong_items", "due_reviews", "get_mastery", "get_train_summary",
    "list_recordings", "write_study_file", "run_code",
    "open_file", "launch_app", "open_url", "browser_status", "browser_history",
]
