"""托盘与启动项：托盘菜单、显示横栏、开机自启、后台守护。"""
from __future__ import annotations

import os
import pathlib

from PySide6 import QtCore, QtWidgets

from learnsys import config, product
from learnsys.ask import guard, icon as icon_mod, shortcuts, bar
from .web_service import (_pythonw, _tray_icon, launcher_target, version_line,
                          watchdog_command)


class TrayMixin:
    # ---- 托盘 ----

    def _build_tray(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(_tray_icon(), self)
        menu = QtWidgets.QMenu()
        menu.addAction(f"框选提问（{self.hotkey.pretty}）", self.pick)
        menu.addSeparator()
        self.record_action = menu.addAction("开始录像（主屏+系统声音）")
        self.record_action.setCheckable(True)
        self.record_action.triggered.connect(self._toggle_record)
        menu.addAction("展开横栏", self.show_bar)
        menu.addAction(f"打开{product.PRODUCT_NAME}（独立窗口）", self.open_web)
        menu.addAction("设置（Qt 试点）", self.open_qt_settings)
        menu.addAction("今日（Qt 试点）", self.open_qt_today)
        menu.addAction("收起成小条", lambda: self.bar.set_collapsed(True))
        menu.addAction("回到屏幕上方居中", self.bar.center_top)
        menu.addAction("打开今天的数据文件夹", self.open_today)
        menu.addAction("番茄钟（25 分钟专注）", self._start_pomodoro)
        menu.addAction("挂载课件来问（PDF/DOCX/PPTX/TXT）", self._attach_doc)
        menu.addAction("生成今天的术语表", self._generate_glossary)
        menu.addAction("今天学了多久（专注统计）", self._show_focus)
        menu.addAction("导出错题本（Anki CSV）", self._export_anki)
        menu.addAction("生成今天的学习报告（Markdown）", self._generate_report)
        menu.addAction("导出今天的对话笔记（Markdown）", self._export_notes)
        menu.addAction("立即备份数据", self._backup_now)
        menu.addSeparator()
        self.startup_action = menu.addAction("开机自启（跟着电脑一起起来）")
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self._startup_on())
        self.startup_action.triggered.connect(self._toggle_startup)
        self.guard_action = menu.addAction("后台守护（掉线一分钟内自动拉起）")
        self.guard_action.setCheckable(True)
        self.guard_action.setChecked(guard.task_installed())
        self.guard_action.triggered.connect(self._toggle_guard)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        tray.setContextMenu(menu)
        menu.setStyleSheet(bar.QSS)   # 托盘菜单也吃同一套深色样式 —— 不然弹出来是刺眼的白
        tray.setToolTip(f"{product.PRODUCT_NAME} {version_line()}\n按 {self.hotkey.pretty} 框选屏幕；横栏能拖着挪、也能收成小条。")
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

    def _startup_on(self) -> bool:
        try:
            return (shortcuts.startup_dir() / product.STARTUP_LNK_NAME).exists()
        except Exception:
            return False

    def _toggle_startup(self) -> None:
        target = shortcuts.startup_dir() / product.STARTUP_LNK_NAME
        try:
            if target.exists():
                target.unlink()
                want = False
            else:
                icon_path = icon_mod.ensure_ico()
                if icon_path is None:
                    self._warn("图标还没生成，开机自启先放一放。")
                    return
                if config.FROZEN:      # 打包后：Startup 直接拉起 exe 自己
                    exe = launcher_target()
                    arguments, workdir = "--background", exe.parent
                else:                  # 源码：pythonw -m learnsys.ask.app --background
                    exe = pathlib.Path(_pythonw())
                    arguments, workdir = "-m learnsys.ask.app --background", config.ROOT
                want = shortcuts.make_startup_shortcut(
                    exe, icon_path, arguments=arguments, working_dir=workdir) is not None
        except Exception as exc:
            self._warn(f"改开机自启没成功：{exc}")
            return
        if hasattr(self, "startup_action"):
            self.startup_action.setChecked(want)
        self._warn(f"已设为开机自启 —— 下次开机自动起后台和横栏。" if want
                   else "已关掉开机自启。")

    def _toggle_guard(self) -> None:
        """后台守护：Windows 计划任务每分钟检查一次，后台掉了就拉起来。"""
        try:
            if guard.task_installed():
                ok, message = guard.remove_task()
            else:
                ok, message = guard.install_task(watchdog_command())
        except Exception as exc:
            self._warn(f"改后台守护没成功：{exc}")
            return
        if hasattr(self, "guard_action"):
            self.guard_action.setChecked(guard.task_installed())
        self._warn(message)
