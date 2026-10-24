"""启动后台任务：备份、清理旧数据、查新版本、错题提醒。"""
from __future__ import annotations

import pathlib

from PySide6 import QtCore

from learnsys import config, store
from learnsys.ask import backup
from learnsys.services import study
from .web_service import check_new_version


class _StartupWorker(QtCore.QThread):
    """启动时后台干的杂活：该备份就备份、keep_days 清理、查新版本。message 逐条发。"""

    message = QtCore.Signal(str)

    def __init__(self, data_root: pathlib.Path, backup_dir: pathlib.Path, parent=None):
        super().__init__(parent)
        self._data_root = data_root
        self._backup_dir = backup_dir

    def run(self):
        keep_days = config._user_int("keep_days", 0)
        if keep_days > 0:
            try:
                removed = backup.prune_old_days(self._data_root, keep_days)
                if removed:
                    self.message.emit(f"已按设置清理 {keep_days} 天前的数据：" + "、".join(removed))
            except Exception:
                pass
        if backup.needs_backup(self._backup_dir):
            try:
                zip_path = backup.do_backup(self._data_root, self._backup_dir)
                self.message.emit(f"自动备份完成：{zip_path}")
            except Exception as exc:
                self.message.emit(f"自动备份没成功：{exc}")
        newer = check_new_version()
        if newer:
            self.message.emit(f"发现新版本 {newer} —— 到 GitHub 的 Releases 页下载更新。")
        # 错题本复习提醒（1/3/7 天节奏，跨所有日子查）。
        # 只提醒不推进度 —— 有没有复习由错题本页面「记住了 / 没记住」决定，
        # 否则用户还没打开就被记成复习过一次。
        import datetime as _dt
        due_total = 0
        try:
            for _day, db_path in study.storage_dbs(self._data_root):
                conn = store.connect(db_path)
                try:
                    due_total += len(store.wrong_due_items(conn, _dt.date.today()))
                finally:
                    conn.close()
        except Exception:
            pass
        if due_total:
            self.message.emit(f"错题本有 {due_total} 题到复习期了 —— 打开工作台的「错题本」过一遍。")


class _BackupWorker(QtCore.QThread):
    """备份在后台打包（数据上百 MB 时不能卡界面）。done 发 zip 路径或 Exception。"""

    done = QtCore.Signal(object)

    def __init__(self, data_root: pathlib.Path, backup_dir: pathlib.Path, parent=None):
        super().__init__(parent)
        self._data_root = data_root
        self._backup_dir = backup_dir

    def run(self):
        try:
            self.done.emit(backup.do_backup(self._data_root, self._backup_dir))
        except Exception as exc:                 # 后台线程的异常别吞
            self.done.emit(exc)
