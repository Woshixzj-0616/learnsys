"""Qt 试点入口：打开设置窗口 / 今日页。

R3.1 先给 `--qt-settings` 用；R3.8 接托盘菜单与单实例；R4 增加今日页。
"""
from __future__ import annotations


def open_workbench_link(port: int, href: str) -> str:
    """把 `#/...` 深链交给 Web 工作台；已有窗口时只聚焦（R4 已知限制）。"""
    from learnsys.ask import workbench

    text = str(href or "#/today")
    if text.startswith(("http://", "https://")):
        url = text
    elif text.startswith("/"):
        url = f"http://127.0.0.1:{int(port)}{text}"
    else:
        url = f"http://127.0.0.1:{int(port)}/{text if text.startswith('#') else '#/' + text}"
    return workbench.open_or_focus(url)


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

    def open_qt_today(self) -> None:
        """打开（或聚焦）今日页；每次打开都重新拉数据。"""
        port = int(getattr(self, "_web_port", 0) or 0)
        if not port:
            self._warn("本地服务还没起来，等几秒再点「今日（Qt 试点）」。")
            return

        from learnsys.ask.qt.api import ApiClient
        from learnsys.ask.qt.today import TodayWindow

        window = getattr(self, "_qt_today_window", None)
        if window is None:
            window = TodayWindow(
                ApiClient(port),
                navigate=lambda href: open_workbench_link(port, href),
                open_settings=self.open_qt_settings,
            )
            self._qt_today_window = window
        window.show()
        window.raise_()
        window.activateWindow()
        window.load()
