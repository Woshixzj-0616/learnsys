"""本机可读目录的索引表（P34.2）。

只存文件名/路径/大小/修改时间，不存正文；敏感文件与排除目录在写入前就过滤掉。
`indexed_at` 是本轮扫描的时间戳，用「标记-清除」删除已消失的文件 —— 不拼巨大的 IN 列表。
"""

LOCAL_FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root       TEXT NOT NULL,                    -- 所属白名单目录
    path       TEXT NOT NULL,                    -- 完整路径
    name       TEXT NOT NULL,                    -- 原始文件名
    name_l     TEXT NOT NULL,                    -- casefold 文件名
    path_l     TEXT NOT NULL,                    -- casefold 全路径
    ext        TEXT NOT NULL DEFAULT '',
    size       INTEGER NOT NULL DEFAULT 0,
    mtime_ns   INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL DEFAULT ''          -- 本轮扫描标记
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_local_files_path
    ON local_files (path);
CREATE INDEX IF NOT EXISTS idx_local_files_root
    ON local_files (root, indexed_at);
CREATE INDEX IF NOT EXISTS idx_local_files_ext
    ON local_files (ext, mtime_ns DESC);

CREATE TABLE IF NOT EXISTS local_file_roots (
    root       TEXT PRIMARY KEY,
    scanned_at TEXT NOT NULL DEFAULT '',
    file_count INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'ok',       -- ok | missing | truncated | error
    note       TEXT NOT NULL DEFAULT ''
);
"""
