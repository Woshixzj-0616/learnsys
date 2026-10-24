"""Qt 试点入口：打开设置窗口 / 今日页。

R3.1 先给 `--qt-settings` 用；R3.8 接托盘菜单与单实例；R4 增加今日页；
R6 起深链点击会先写服务端队列，已有 Web 窗口也能跳转（B1 深链桥）。
"""
from __future__ import annotations


def open_workbench_link(port: int, href: str, *, has_window=None, post=None,
                        focus=None, open_url=None) -> str:
    """把 `#/...` 深链交给 Web 工作台。

    - 已有 Web 窗口：先写待跳转队列，再把窗口提到前台（页面聚焦时立即拉取）。
    - 没有窗口：新开一个直接带 hash 的窗口。
    参数可注入，测试不发真实网络、不动真实窗口。
    """
    from learnsys.ask import workbench
    from learnsys.ask.desktop import deep_link

    has_window = has_window or workbench.has_web_window
    open_url = open_url or workbench.open_or_focus
    target = deep_link.hash_target(href)
    url = deep_link.workbench_url(port, href)
    if not target or not has_window():
        return open_url(url)
    sender = post or deep_link.post_navigate
    sent = bool(sender(int(port), target))
    (focus or workbench.focus_window)()
    return "已聚焦现有学习工作台" if sent else "已聚焦现有学习工作台（跳转请求没发出去）"


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
