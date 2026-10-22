"""数据备份：手动 / 自动打包，后台线程执行。"""
from __future__ import annotations

from PySide6 import QtWidgets

from learnsys import config, product
from .startup import _BackupWorker


class DataBackupMixin:
    # ---- 数据备份 ----

    def _backup_now(self) -> None:
        self._run_backup(manual=True)

    def _run_backup(self, manual: bool) -> None:
        if self._backup_worker is not None and self._backup_worker.isRunning():
            self._warn("上一次备份还在打包 —— 等它一下。")
            return
        worker = _BackupWorker(config.DATA_ROOT, self._backup_dir, self)
        worker.done.connect(lambda result, m=manual: self._backup_done(result, m))
        worker.finished.connect(worker.deleteLater)
        self._backup_worker = worker
        worker.start()
        if manual:
            self.bar.show_message("正在打包备份 …… 打完会告诉你放哪儿了。")

    def _backup_done(self, result, manual: bool) -> None:
        self._backup_worker = None
        if isinstance(result, Exception):
            self._warn(f"备份没成功：{result}")
            return
        if manual:
            self._warn(f"备份好了：{result}")
        else:
            self.tray.showMessage(
                product.PRODUCT_NAME, f"自动备份完成：{result}（每周一次，可在 设置.json 里改 backup_dir 换地方）",
                QtWidgets.QSystemTrayIcon.Information, 8000)
