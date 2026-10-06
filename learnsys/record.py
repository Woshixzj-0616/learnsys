"""采集层（最小版）：记下「你在看哪个窗口」。

口径是 09-23 定的，没变：
- **手动开始 / 结束**，不全天记录（开学才记，下课就停）
- 只采前台窗口，**不开麦克风**，采集时零模型调用
- **窗口变了才记一条** —— 不是每秒都记 ⇒ 一行 = 一次切换，数据量小、复盘时好算
- 数据只在本地，按天落在 `D:\\学习系统\\<年.月.日>\\`

这一层只负责「把时间轴攒起来」。以后问「我刚才漏了什么」，查的就是它。
"""
from __future__ import annotations

from PySide6 import QtCore

from learnsys import capture, config, store


class WindowRecorder(QtCore.QObject):
    """每秒看一眼前台窗口，变了才记一条。用 Qt 的定时器，不开新线程。"""

    ticked = QtCore.Signal()      # 每秒到一下 —— 界面拿它刷「记录中 几分」

    def __init__(self, conn_getter, parent=None):
        super().__init__(parent)
        self._conn_getter = conn_getter
        self._conn = None
        self._session_id = None
        self._db_path = None
        self._started_at = ""
        self._switches = 0        # 这段记了多少条 = 切了多少次窗口
        self._last = None         # 上一次看到的 (程序名, 标题)，没变就不记
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(max(200, int(config.WINDOW_SAMPLE_SECONDS * 1000)))
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self._session_id is not None

    @property
    def elapsed(self) -> float:
        """已经记了多少分钟。"""
        if not self._started_at:
            return 0.0
        return round(store.minutes(self._started_at, store.now()), 1)

    @property
    def switches(self) -> int:
        """这段记了多少条 = 切了多少次窗口。"""
        return self._switches

    def start(self) -> None:
        if self.running:
            return
        self._conn = self._conn_getter()
        self._db_path = config.db_path()
        self._session_id = store.start_session(self._conn)
        self._started_at = store.now()
        self._switches = 0
        self._last = None
        self._timer.start()
        self._tick()              # 立刻记第一条，别等一秒

    def stop(self) -> dict:
        """结束这段记录，返回一句话总结（记了多久 / 切了几次 / 最久停在哪个）。"""
        if not self.running:
            return {}
        self._timer.stop()
        try:
            store.end_session(self._conn, self._session_id)
            summary = store.session_summary(self._conn, self._session_id)
        except Exception:
            summary = {}          # 连接万一被换掉过，别让「结束记录」整个崩掉
        self._session_id = None
        self._last = None
        return summary

    def _tick(self) -> None:
        want = config.db_path()
        if want != self._db_path:
            # 过了零点换了库 ⇒ 先在昨天那段收尾，再在新的一天接着开一段
            try:
                store.end_session(self._conn, self._session_id)
            except Exception:
                pass              # 旧连接万一已不可用，新一天照样开
            self._conn = self._conn_getter()
            self._db_path = want
            self._session_id = store.start_session(self._conn)
            self._started_at = store.now()
            self._last = None
            self._switches = 0           # 新的一段从头计 —— 原来这里漏了，数字会跨天累加

        process, title = capture.sample()
        title = title if config.RECORD_WINDOW_TITLE else ""
        if not (process or title):
            self.ticked.emit()
            return
        if (process, title) == self._last:
            self.ticked.emit()               # 还看着同一个窗口，不重复记
            return
        first = self._last is None           # 第一条是「开始看的窗口」，不算切换
        self._last = (process, title)
        store.add_window_event(self._conn, self._session_id, process, title)
        if not first:
            self._switches += 1
        self.ticked.emit()
