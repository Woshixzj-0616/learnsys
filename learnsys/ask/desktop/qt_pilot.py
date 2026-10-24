"""Qt 试点入口：打开设置窗口。

R3.1 先给 `--qt-settings` 用；R3.8 再接托盘菜单与单实例。
"""
from __future__ import annotations


class QtPilotMixin:
    def open_qt_settings(self) -> None:
        """打开（或聚焦）同一个设置窗口；每次打开都重新拉数据。"""
        port = int(getattr(self, "_web_port", 0) or 0)
        if not port:
            self._warn("本地服务还没起来，等几秒再点「设置（Qt 试点）」。")
            return

        from learnsys.ask.qt.api import ApiClient
        from learnsys.ask.qt.settings import SettingsWindow

        window = getattr(self, "_qt_settings_window", None)
        if window is None:
            window = SettingsWindow(ApiClient(port))
            self._qt_settings_window = window
        window.show()
        window.raise_()
        window.activateWindow()
        window.load()
