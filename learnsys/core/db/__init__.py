"""学习工作台 v2 的统一数据库。

按职责拆到 schema / connection / migrate / fts；这里原样导出，
`from learnsys.core import db as core_db` 的调用点不用改。
"""
from __future__ import annotations

from .connection import _LOCK, connect, counts, now
from .fts import _ensure_fts, fts_ready, index_row, search
from .migrate import (_day_dbs, _import_legacy_starred, _import_starred_rows,
                      _migrate_columns, _migrate_one, _table_rows, migrate_from_v1)
from .schema import FTS_SCHEMA, SCHEMA

__all__ = [
    "SCHEMA", "FTS_SCHEMA", "connect", "now", "counts",
    "_migrate_columns", "_ensure_fts", "_import_starred_rows",
    "_import_legacy_starred", "fts_ready", "index_row", "search",
    "_day_dbs", "_table_rows", "migrate_from_v1", "_migrate_one",
]
