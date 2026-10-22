"""存储层共享底座：数据库连接、时间格式、全局写锁、schema 引用。

各业务域模块共用同一把 `_LOCK` —— 连接会被后台线程共用，
每个子模块各建一把锁等于没有锁。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading

from learnsys.core import db as core_db


SCHEMA = core_db.SCHEMA

_LOCK = threading.Lock()


def connect(path=None) -> sqlite3.Connection:
    """注意：连接会被后台线程共用，所以关掉同线程检查，写操作用 _LOCK 串起来。"""
    return core_db.connect(path)


def _migrate(conn: sqlite3.Connection) -> None:
    """兼容旧调用：老库补列（真正的实现在 core.db）。"""
    core_db._migrate_columns(conn)


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")
