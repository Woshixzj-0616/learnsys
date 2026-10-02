"""问一问 · 入口：托盘 + 全局热键 + 框选 + 顶部横栏。

双击「问一问.cmd」让它常驻：启动就在屏幕上方出一条横栏（上面写着本程序占了多少盘），
按 Alt+Q（或点横栏上的「框选」）框一块屏幕，就在那条横栏里问它。
数据存在 D 盘专用文件夹里、按天分：D:\学习系统\2026.10.2\（那天的库 + 那天的截图）；**打开 app 就先把当天的文件夹建出来**。
"""
from __future__ import annotations

import os
import pathlib
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config, store
from learnsys.ask import bar, hotkey as hotkey_mod, icon as icon_mod, identity, overlay, single

LAUNCHER_NAME = "问一问.cmd"      # 源码运行时那个启动器：开机自启、开始菜单快捷方式都指向它


def launcher_target() -> pathlib.Path:
    """「问一问」是怎么被起来的：**打包后 = 它自己的 exe**；源码跑 = 项目里那个 .cmd。"""
    if config.FROZEN:
        return pathlib.Path(sys.executable).resolve()
    return config.ROOT / LAUNCHER_NAME


def _silence_windowed() -> None:
    """打包成「没有黑框」之后 stdout / stderr 是 None —— 兜个黑洞，免得哪句 print 把程序炸了。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def _pythonw() -> str:
    """挑一个不弹黑框的解释器（跟 问一问.cmd 同一个顺序）。"""
    for candidate in (config.ROOT / ".venv" / "Scripts" / "pythonw.exe",
                      pathlib.Path(r"D:\Desktop\bilinote\asr-venv\Scripts\pythonw.exe"),
                      pathlib.Path(r"D:\python\pythonw.exe")):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _tray_icon() -> QtGui.QIcon:
    """托盘 / 窗口 / 任务栏共用那一张 —— 画法只在 learnsys/ask/icon.py 一处。"""
    return icon_mod.icon()


class AskApp(QtCore.QObject):
    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self.app = app
        self.conn = None
        self._conn_path = None
        self.snip = None
        self.hotkey = hotkey_mod.GlobalHotkey(config.ASK_HOTKEY)
        self.hotkey.triggered.connect(self.pick)
        self.hotkey.failed.connect(self._warn)
        self.bar = bar.AskBar(self.hotkey.pretty)     # 全程序唯一一条横栏
        self.bar.pick_requested.connect(self.pick)
        self.bar.answered.connect(self._remember)
        self.bar.exited.connect(self._shot_done)
        self.bar.history_provider = self._recent_asks
        self.caller = single.Server(self)      # 别人再点一次 → 把横栏叫回来（不再开第二个）
        self.caller.called.connect(self._called_back)
        self.tray = self._build_tray()

    # ---- 托盘 ----

    def _build_tray(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(_tray_icon(), self)
        menu = QtWidgets.QMenu()
        menu.addAction(f"框选提问（{self.hotkey.pretty}）", self.pick)
        menu.addAction("展开横栏", self.show_bar)
        menu.addAction("收起成小条", lambda: self.bar.set_collapsed(True))
        menu.addAction("回到屏幕上方居中", self.bar.center_top)
        menu.addAction("打开今天的数据文件夹", self.open_today)
        menu.addAction("怎么固定到任务栏…", self._pin_help)
        menu.addAction("修复任务栏固定（指回问一问）", self._fix_pin)
        menu.addSeparator()
        self.startup_action = menu.addAction("开机自启（跟着电脑一起起来）")
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self._startup_on())
        self.startup_action.triggered.connect(self._toggle_startup)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        tray.setContextMenu(menu)
        tray.setToolTip(f"问一问 · 按 {self.hotkey.pretty} 框选屏幕")
        tray.activated.connect(self._tray_clicked)
        tray.show()
        return tray

    def _tray_clicked(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show_bar()
        elif reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self.pick()

    def show_bar(self) -> None:
        # 被「最小化 / Win+D」藏起来时，光 show() 是回不来的 —— 先把最小化状态摘掉
        self.bar.setWindowState(self.bar.windowState() & ~QtCore.Qt.WindowMinimized)
        self.bar.show()
        self.bar.raise_()

    def start(self) -> None:
        day = self.prepare_today()          # 打开 app 就先把当天的文件夹建出来
        self._install_identity()            # 给自己的任务栏身份收尾（别再被 Windows 当成 IDLE）
        ready = self.hotkey.register()      # 快捷键被占了也别把界面藏起来
        self.show_bar()
        self.bar.show_message(f"今天的数据放这儿：{day}")
        if ready:
            self.tray.showMessage(
                "问一问",
                f"已就绪 —— 按 {self.hotkey.pretty} 框一块屏幕；横栏能拖着挪、也能收成小条。",
                QtWidgets.QSystemTrayIcon.Information, 5000)

    def _install_identity(self) -> None:
        """任务栏身份收尾：自己的图标 + HKCU 注册 + 开始菜单快捷方式。"""
        icon_path = icon_mod.ensure_ico()
        if icon_path is None:
            return
        if identity.install(launcher_target(), icon_path)["shortcut"] is None:
            print("开始菜单快捷方式没摆上 —— 固定到任务栏可能得手动来", file=sys.stderr)
        # 每次启动顺手把任务栏那条固定修回来：Windows 是照「跑它的那个 exe」建的它
        # （目标是裸 exe、图标空）⇒ 一启动就把它指回问一问 + 咱的图标。
        identity.repair_taskbar_pins(launcher_target(), icon_path)

    def _pin_help(self) -> None:
        """「固定到任务栏」怎么才对：别再固定成 IDLE 那条。"""
        text = identity.PIN_HELP_FROZEN if config.FROZEN else identity.PIN_HELP
        self.tray.showMessage("问一问", text,
                              QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message(text.replace(chr(10), " "))
        self.show_bar()

    def _fix_pin(self) -> None:
        """任务栏那条固定若指着裸 pythonw（点不开）—— 把它指回 问一问.cmd。"""
        icon_path = icon_mod.ensure_ico()
        if icon_path is None:
            self._warn("图标还没生成，先放一放。")
            return
        fixed = identity.repair_taskbar_pins(launcher_target(), icon_path)
        self._warn("修好了 %d 条任务栏固定。" % fixed if fixed
                   else "没找到要修的（先在任务栏上固定一条，再点这个）。")

    def _called_back(self) -> None:
        """又点了一次「问一问」—— 把横栏露出来给他看。"""
        self.show_bar()
        self.bar.show_message("问一问已经在跑了 —— 把横栏给你叫回来了。")

    def quit(self) -> None:
        self.caller.close()
        self._shot_done()
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self.app.quit()

    # ---- 开机自启 ----

    def prepare_today(self) -> pathlib.Path:
        """打开 app 就把「今天」那个文件夹建出来（已经有的不动），顺手摆一份设置模板。"""
        config.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        day = config.day_dir()
        day.mkdir(parents=True, exist_ok=True)
        config.ensure_settings_file()
        return day

    def open_today(self) -> None:
        """在资源管理器里打开今天的数据文件夹。"""
        try:
            os.startfile(str(self.prepare_today()))
        except Exception as exc:
            self._warn(f"打不开文件夹：{exc}")

    def _startup_dir(self) -> pathlib.Path:
        base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
        return (pathlib.Path(base) / "Microsoft" / "Windows" / "Start Menu"
                / "Programs" / "Startup")

    def _startup_on(self) -> bool:
        try:
            return (self._startup_dir() / LAUNCHER_NAME).exists()
        except Exception:
            return False

    def _toggle_startup(self) -> None:
        target = self._startup_dir() / LAUNCHER_NAME
        try:
            if target.exists():
                target.unlink()
                want = False
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if config.FROZEN:      # 打包后：开机自启直接拉起 exe 自己
                    lines = ["@echo off", f'start "" "{launcher_target()}"']
                else:
                    lines = ["@echo off",
                             f'cd /d "{config.ROOT}"',
                             f'start "" "{_pythonw()}" -m learnsys.ask.app']
                target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
                want = True
        except Exception as exc:
            self._warn(f"改开机自启没成功：{exc}")
            return
        if hasattr(self, "startup_action"):
            self.startup_action.setChecked(want)
        self._warn("已设为开机自启 —— 下次开机自动出横栏。" if want else "已关掉开机自启。")

    # ---- 框选 → 截图 → 横栏 ----

    def pick(self) -> None:
        if self.snip is not None or self.bar.busy:
            return
        self.bar.hide()                  # 别把自己框进去
        self.snip = overlay.Overlay()
        self.snip.selected.connect(self._region_chosen)
        self.snip.cancelled.connect(self._pick_cancelled)
        self.snip.show()

    def _pick_cancelled(self) -> None:
        self.snip = None
        self.show_bar()                  # 框选取消 → 横栏原样回来

    def _region_chosen(self, rect: QtCore.QRect) -> None:
        self.snip = None
        QtCore.QTimer.singleShot(140, lambda: self._capture(rect))

    def _capture(self, rect: QtCore.QRect) -> None:
        screen = QtGui.QGuiApplication.screenAt(rect.center()) or QtGui.QGuiApplication.primaryScreen()
        geo = screen.geometry()
        shot = screen.grabWindow(0, rect.x() - geo.x(), rect.y() - geo.y(),
                                 rect.width(), rect.height())
        if shot.isNull() or shot.width() == 0 or shot.height() == 0:
            self._warn("这块没抓到东西，再框一次试试。")
            return
        self._shot_done()                # 上一张先清掉：盘上任何时候只有一张
        image_path = self._shot_path()
        image_path.parent.mkdir(parents=True, exist_ok=True)
        if not shot.save(str(image_path), "PNG"):
            self._warn("截图存不下来，再框一次试试。")
            return
        self.bar.set_shot(str(image_path), shot)
        self.show_bar()

    # ---- 收尾 ----

    def _conn(self):
        """今天的库 —— 跨天了（过了零点）自动换到新一天那个文件夹。"""
        want = config.db_path()
        if self.conn is None or self._conn_path != want:
            if self.conn is not None:
                try:
                    self.conn.close()
                except Exception:
                    pass
            self.conn = store.connect(want)
            self._conn_path = want
        return self.conn

    def _remember(self, question: str, answer: str, ms: int) -> None:
        try:
            store.add_ask(self._conn(), question, answer, ms, "codex")
        except Exception as exc:
            print(f"写库失败：{exc}", file=sys.stderr)
        self.bar.refresh_usage()         # 答案落库 ⇒ 占用数字跟着变

    def _recent_asks(self):
        """给横栏「历史」按钮用：今天的问答（新→旧）。"""
        try:
            return store.recent_asks(self._conn(), limit=20)
        except Exception as exc:
            print(f"读历史失败：{exc}", file=sys.stderr)
            return []

    def _shot_path(self) -> pathlib.Path:
        return config.ask_tmp_dir() / "shot.png"

    def _shot_done(self) -> None:
        """临时截图收尾：问完即删（ASK_KEEP_IMAGES = True 时留着不动）。"""
        if config.ASK_KEEP_IMAGES:
            return
        folder = config.ask_tmp_dir()
        try:
            for item in folder.glob("*"):
                item.unlink()
            folder.rmdir()
        except OSError:
            pass

    def _warn(self, message: str) -> None:
        self.tray.showMessage("问一问", message, QtWidgets.QSystemTrayIcon.Warning, 6000)
        self.bar.show_message(message)
        self.show_bar()


def main() -> int:
    _silence_windowed()                   # 无黑框模式：print 不能炸
    identity.declare_process_identity()   # 必须在建窗口之前：Windows 认的是这个，不是 exe
    app = QtWidgets.QApplication(sys.argv)
    if not single.claim():                # 已经有一个在跑了 → 叫它露个脸，自己退
        return 0
    app.setApplicationName("learnsys-ask")
    app.setQuitOnLastWindowClosed(False)
    ask_app = AskApp(app)
    app.aboutToQuit.connect(ask_app.hotkey.unregister)
    QtCore.QTimer.singleShot(0, ask_app.start)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
