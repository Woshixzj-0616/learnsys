"""本地 SQLite 存储（唯一读写入口）。

按业务域拆到子模块；这里把公共函数原样导出，调用方继续用 `store.xxx`。
真正的表结构在 `learnsys/core/db`。
"""
from __future__ import annotations

from ._base import SCHEMA, _LOCK, _migrate, connect, now, stamp
from .agent_runs import add_agent_run, get_agent_run, list_agent_runs, route_stats
from .asks import add_ask, recent_asks, starred_asks
from .browser import (add_browser_event, cleanup_browser_events,
                      clear_browser_events, list_browser_events)
from .cet6 import (add_cet6_dualwrite_diffs, add_cet6_dualwrite_run,
                   cet6_progress_item, cet6_progress_paper_rows,
                   cet6_progress_summary, cet6_recent_events,
                   upsert_cet6_progress)
from .conversations import (add_message, conversation_messages, create_conversation,
                            get_conversation, list_conversations, touch_conversation)
from .events import add_event
from .knowledge import (BKT_READY_SQL, add_attempt as add_knowledge_attempt,
                        all_points as knowledge_points, attempt_exists,
                        backfill_candidates, has_live_attempt, meta_value as knowledge_meta,
                        point_attempts as knowledge_point_attempts,
                        point_by_id as knowledge_point, ready_attempts,
                        set_meta as set_knowledge_meta, stats as knowledge_stats,
                        meta_value, set_meta)
from .materials import (MATERIAL_KINDS, add_material, delete_material_row, get_material,
                        list_materials, material_counts, set_material_status,
                        touch_material, update_material)
from .memories import add_memory, delete_memory, list_memories, update_memory
from .review import (REVIEW_ITEM_TYPES, add_review_log, due_review_items,
                     get_review_state, recent_review_log, review_stats,
                     save_review_state, seed_review_states)
from .study import (add_frame_text, add_transcript, add_window_event,
                    add_window_event_at, end_session, focus_stats, frame_text_between,
                    last_transcript, minutes, search_transcripts, session_stats,
                    session_summary, session_windows, start_session, window_titles)
from .vocab import (add_vocab, delete_vocab, export_vocab, get_vocab, import_vocab,
                    list_vocab, update_vocab)
from .wrongbook import (WRONG_SOURCES, add_wrong_item, bump_review_stage,
                        delete_wrong_item, due_starred, get_wrong_item,
                        review_wrong_item, set_wrong_mastered, toggle_ask_wrong,
                        toggle_star, wrong_counts, wrong_due_items,
                        wrong_fingerprint, wrong_items, wrong_material_facets)

__all__ = [
    "SCHEMA", "connect", "now", "stamp",
    "add_agent_run", "get_agent_run", "list_agent_runs", "route_stats",
    "add_ask", "recent_asks", "starred_asks",
    "add_browser_event", "cleanup_browser_events", "clear_browser_events",
    "list_browser_events",
    "cet6_progress_item", "cet6_progress_summary", "cet6_recent_events",
    "cet6_progress_paper_rows", "add_cet6_dualwrite_run",
    "add_cet6_dualwrite_diffs", "upsert_cet6_progress",
    "add_message", "conversation_messages", "create_conversation",
    "get_conversation", "list_conversations", "touch_conversation",
    "add_event",
    "BKT_READY_SQL", "add_knowledge_attempt", "knowledge_points",
    "attempt_exists", "backfill_candidates", "has_live_attempt",
    "knowledge_meta", "knowledge_point_attempts", "knowledge_point",
    "ready_attempts", "set_knowledge_meta", "knowledge_stats",
    "meta_value", "set_meta",
    "MATERIAL_KINDS", "add_material", "delete_material_row", "get_material",
    "list_materials", "material_counts", "set_material_status", "touch_material",
    "update_material",
    "add_memory", "delete_memory", "list_memories", "update_memory",
    "REVIEW_ITEM_TYPES", "add_review_log", "due_review_items", "get_review_state",
    "recent_review_log", "review_stats", "save_review_state", "seed_review_states",
    "add_frame_text", "add_transcript", "add_window_event", "add_window_event_at",
    "end_session", "focus_stats", "frame_text_between", "last_transcript",
    "minutes", "search_transcripts", "session_stats", "session_summary",
    "session_windows", "start_session", "window_titles",
    "add_vocab", "delete_vocab", "export_vocab", "get_vocab", "import_vocab",
    "list_vocab", "update_vocab",
    "WRONG_SOURCES", "add_wrong_item", "bump_review_stage", "delete_wrong_item",
    "due_starred", "get_wrong_item", "review_wrong_item", "set_wrong_mastered",
    "toggle_ask_wrong", "toggle_star", "wrong_counts", "wrong_due_items",
    "wrong_fingerprint", "wrong_items", "wrong_material_facets",
]
