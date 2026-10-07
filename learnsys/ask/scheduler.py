"""小定时器框架：提醒 / 番茄钟 / 定时停止都挂在这里。

会话级（不跨重启）—— 重启后还没响的提醒就没了，这是刻意的：提醒是「趁我在电脑前」的事。
"""
from __future__ import annotations

from PySide6 import QtCore


class Scheduler(QtCore.QObject):
    """按名字挂一次性定时任务，到点发 fired(名字, 附带数据)。同名字重复挂 = 覆盖旧的。"""

    fired = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timers: dict[str, QtCore.QTimer] = {}
        self._payloads: dict[str, object] = {}

    def after(self, name: str, seconds: float, payload: object = None) -> None:
        self.cancel(name)
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        self._payloads[name] = payload
        timer.timeout.connect(lambda: self._fire(name))
        self._timers[name] = timer
        timer.start(max(1, int(seconds * 1000)))

    def cancel(self, name: str) -> None:
        timer = self._timers.pop(name, None)
        self._payloads.pop(name, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def pending(self, name: str) -> bool:
        return name in self._timers

    def _fire(self, name: str) -> None:
        self._timers.pop(name, None)
        self.fired.emit(name, self._payloads.pop(name, None))
