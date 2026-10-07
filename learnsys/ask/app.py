"""问一问 · 入口：托盘 + 全局热键 + 框选 + 顶部横栏。

双击「问一问.cmd」让它常驻：启动就在屏幕上方出一条横栏（上面写着本程序占了多少盘），
按 Alt+Q（或点横栏上的「框选」）框一块屏幕，就在那条横栏里问它。
数据存在 D 盘专用文件夹里、按天分：D:\学习系统\2026.10.2\（那天的库 + 那天的截图）；**打开 app 就先把当天的文件夹建出来**。
"""
from __future__ import annotations

import datetime
import os
import pathlib
import shutil
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config, record, store
from learnsys.ask import VERSION, backup, bar, hotkey as hotkey_mod, icon as icon_mod, study
from learnsys.ask import backend, identity, liverec, ocr, ops, overlay, single, scheduler

LAUNCHER_NAME = "问一问.cmd"      # 源码运行时那个启动器：开机自启、开始菜单快捷方式都指向它
NL = chr(92) + "n"               # 写进文件/字符串字面量里的「反斜杠+n」（换行转义）


def version_line() -> str:
    """给托盘 / 启动提示用的一行版本：打包后带打包日期，源码跑就标「源码」。"""
    if config.FROZEN:
        try:
            day = datetime.date.fromtimestamp(pathlib.Path(sys.executable).stat().st_mtime)
            return f"v{VERSION}（{day.year}-{day.month:02d}-{day.day:02d} 打包）"
        except OSError:
            return f"v{VERSION}"
    return f"v{VERSION}（源码运行）"


def newest_source_mtime(src_dir: pathlib.Path) -> float | None:
    """目录里 *.py 的最新修改时间；目录不存在（exe 被拷去别处了）返回 None。"""
    if not src_dir.is_dir():
        return None
    newest = 0.0
    for p in src_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return newest or None


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


def check_new_version(timeout: float = 4.0) -> str | None:
    """查 GitHub 最新 release，比当前新就返回版本号；网络/解析失败一律静默。"""
    import json as _json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Woshixzj-0616/learnsys/releases/latest",
            headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tag = str(_json.loads(resp.read().decode("utf-8")).get("tag_name") or "")
    except Exception:
        return None
    def nums(t: str) -> tuple:
        parts = [p for p in t.lower().lstrip("v").split(".") if p.isdigit()]
        return tuple(int(x) for x in parts) or (0,)
    return tag if nums(tag) > nums(VERSION) else None


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
        # 错题本复习提醒（1/3/7 天节奏，跨所有日子查）
        import datetime as _dt
        due_total = 0
        try:
            for _day, db_path in study.day_dbs(self._data_root):
                conn = store.connect(db_path)
                try:
                    due = store.due_starred(conn, _dt.date.today())
                    if due:
                        due_total += len(due)
                    store.bump_review_stage(conn, due)
                finally:
                    conn.close()
        except Exception:
            pass
        if due_total:
            self.message.emit(f"错题本有 {due_total} 题到复习期了 —— 点开历史或来一场测验吧。")


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


class AskApp(QtCore.QObject):
    # 框选松手后有 140ms 的截图延迟 —— 这期间再按快捷键不许框出第二个。
    # 放类上：谁都有默认值，别依赖 __init__ 跑过（测试里有 __new__ 裸构造的用法）
    _capture_scheduled = False

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
        # ✕ 只是把界面收进托盘 —— 图和答案都还在，**别在这儿删截图**（删截图只归
        # 「清空 / 换一张 / 退出」管）。以前接在 exited 上，正在问的那轮会被连累。
        self.bar.cleared.connect(self._shot_done)     # 点「清空」⇒ 临时截图也删掉
        self.bar.review_requested.connect(self._review_today)
        self.bar.star_toggled.connect(self._toggle_star)
        self.bar.record_toggled.connect(self._toggle_record)
        self.bar.quiz_requested.connect(self._quiz_today)
        self.bar.report_requested.connect(self._generate_report)
        self.bar.notes_requested.connect(self._export_notes)
        self.bar.anki_requested.connect(self._export_anki)
        self.bar.rec_pause_toggled.connect(self._toggle_pause)
        self.bar.rec_timer_set.connect(lambda m: self.live.set_stop_timer(m))
        self.bar.extra_context_provider = self._transcript_context
        self.bar.history_provider = self._recent_asks
        self.bar.history_days_provider = self._history_days
        self.bar.history_db_path_provider = lambda: str(self._conn_path or config.db_path())
        self._backup_worker = None
        self._backup_dir = (pathlib.Path(config.USER.get("backup_dir"))
                            if config.USER.get("backup_dir")
                            else config.DATA_ROOT.parent / "学习系统备份")
        self.live = liverec.LiveRecorder(self._conn, self)   # 三路录制：声音+屏幕+窗口
        self.scheduler = scheduler.Scheduler(self)           # 提醒/番茄钟/定时都挂这里
        self.scheduler.fired.connect(self._scheduler_fired)
        self.bar.computer_request.connect(self._computer_request)
        self.bar.remind_scheduled.connect(self._schedule_remind)
        self._ocr = ocr.OcrQueue(self._conn, self)           # 快照 OCR 后台队列
        self.live.frame_saved = self._ocr.enqueue            # 快照落盘即进队
        self.live.ticked.connect(self._live_tick)
        self.live.info.connect(self._live_info)
        self.live.stopped.connect(self._live_stopped)
        self.caller = single.Server(self)      # 别人再点一次 → 把横栏叫回来（不再开第二个）
        self.caller.called.connect(self._called_back)
        self.tray = self._build_tray()

    # ---- 托盘 ----

    def _build_tray(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(_tray_icon(), self)
        menu = QtWidgets.QMenu()
        menu.addAction(f"框选提问（{self.hotkey.pretty}）", self.pick)
        menu.addSeparator()
        self.record_action = menu.addAction("开始完整录制（声音+屏幕+窗口）")
        self.record_action.setCheckable(True)
        self.record_action.triggered.connect(self._toggle_record)
        menu.addAction("展开横栏", self.show_bar)
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
        menu.setStyleSheet(bar.QSS)   # 托盘菜单也吃同一套深色样式 —— 不然弹出来是刺眼的白
        tray.setToolTip(f"问一问 {version_line()}\n按 {self.hotkey.pretty} 框选屏幕；横栏能拖着挪、也能收成小条。")
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
        message = f"问一问 {version_line()} ｜ 今天的数据放这儿：{day}"
        if self._exe_is_stale():
            # 「问一问.cmd」优先启动 dist 里的 exe —— 源码改了没重新打包时，
            # 跑的还是旧版，测试结果会让人怀疑人生（真踩过）
            message += "\n⚠️ 源码比 exe 新 —— 现在跑的还是旧版，双击 打包.cmd 重新打包再测。"
        self.bar.show_message(message)
        self._startup_worker = _StartupWorker(config.DATA_ROOT, self._backup_dir, self)
        self._startup_worker.message.connect(
            lambda m: self.tray.showMessage("问一问", m,
                                            QtWidgets.QSystemTrayIcon.Information, 10000))
        self._startup_worker.start()        # 备份/清理/查新版本都在后台
        if ready:
            self.tray.showMessage(
                "问一问",
                f"已就绪 —— 按 {self.hotkey.pretty} 框一块屏幕；横栏能拖着挪、也能收成小条。",
                QtWidgets.QSystemTrayIcon.Information, 5000)

    def _exe_is_stale(self) -> bool:
        """打包出的 exe 是不是比仓库源码旧（只在「exe 就在仓库 dist 里」时才比得出）。"""
        if not config.FROZEN:
            return False
        src_dir = config.ROOT.parent.parent / "learnsys"   # exe 在 dist/问一问/ 下
        newest = newest_source_mtime(src_dir)
        if newest is None:
            return False
        try:
            exe_mtime = pathlib.Path(sys.executable).stat().st_mtime
        except OSError:
            return False
        return newest > exe_mtime + 60      # 放 60 秒余量，打包尾动不动几秒

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

    # ---- 采集层：开始 / 结束完整录制（声音 + 屏幕 + 窗口）----

    def _toggle_record(self, checked: bool = False) -> None:
        """托盘菜单和横栏「录制」按钮共用这一个开关。"""
        if self.live.recording:
            self.live.stop()
            self.bar.show_message("正在收尾 —— 最后一块转写完（最多一两分钟）会汇报总结。")
        else:
            self.live.start()

    def _record_summary(self, done: dict) -> str:
        """结束时那句话：记了多久、切了几次、转写多少、快照多少。"""
        if not done:
            return "这段没记下东西。"
        top_name, top_min = done.get("最久") or ("", 0)
        text = f"录制完成：{done.get('分钟', 0)} 分钟 · 切了 {done.get('切换', 0)} 次窗口"
        chars = int(done.get("转写字数") or 0)
        frames = int(done.get("快照张数") or 0)
        if chars:
            text += f" · 转写 {chars} 字（{done.get('转写条数', 0)} 段）"
        if frames:
            text += f" · 快照 {frames} 张"
        if top_name and top_min:
            text += f"\n最久停在「{top_name}」约 {top_min} 分钟"
        text += f"\n快照在 {done.get('快照目录', '')}；点「复盘」可以让 AI 帮你总结这段。"
        return text

    def _live_tick(self) -> None:
        """每秒：托盘菜单显示进度，横栏显示「● 录制中」+ 转写/快照计数。"""
        on = self.live.recording
        self.record_action.setChecked(on)
        if self.live.finishing:
            self.record_action.setText("结束完整录制（正在收尾转写…）")
            self.bar.set_recording(True, self.live.window_rec.elapsed,
                                   self.live.window_rec.switches, "正在收尾转写…")
        elif on:
            self.record_action.setText(
                f"结束完整录制（已记 {self.live.window_rec.elapsed:.0f} 分 · 转写 {self.live.chars} 字）")
            detail = f"转写 {self.live.chars} 字 · 快照 {self.live.frames} 张"
            if self.live.chars == 0 and not self.live.listening:
                detail += " · 还没听到声音"
            self.bar.set_recording(True, self.live.window_rec.elapsed,
                                   self.live.window_rec.switches, detail)
        else:
            self.record_action.setText("开始完整录制（声音+屏幕+窗口）")
            self.bar.set_recording(False)

    def _live_info(self, text: str) -> None:
        self.bar.show_message(text)

    def _live_stopped(self, summary: dict) -> None:
        text = self._record_summary(summary)
        self.tray.showMessage("问一问", text, QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message(text.replace(chr(10), " "))

    def quit(self) -> None:
        self.bar.shutdown()      # 先把问答线程收干净 —— 还在跑就销毁会崩（QThread）
        if self.live.recording:
            self.live.stop()     # 退出前收尾录制（后台线程写完最后一块，daemon 兜底）
        if self._backup_worker is not None and self._backup_worker.isRunning():
            self._backup_worker.wait(30000)     # 打包到一半别留半个 zip（数据不大，等得起）
        if self.live.recording:
            self.live.stop()      # 退出前收尾录制（转写线程 daemon 兜底）
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
        if self.snip is not None:
            return
        if self._capture_scheduled:      # 上一块刚松手、截图还没落 —— 再按会框出第二个
            return
        if self.bar.busy:
            # 别闷声不响地吞掉 Alt+Q —— 用户只看到「按了没反应」
            self.bar.show_message("上一句还在写 —— 等它写完，或者点「新会话」重开一轮。")
            self.show_bar()
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
        self._capture_scheduled = True
        QtCore.QTimer.singleShot(140, lambda: self._capture(rect))

    def _capture(self, rect: QtCore.QRect) -> None:
        self._capture_scheduled = False
        # 跨屏框选时 `screenAt(center)` 只会取一块屏 ⇒ 按屏裁剪再拼起来，
        # 以前选区横跨两屏时只能抓到半边。
        canvas = QtGui.QImage(rect.width(), rect.height(),
                              QtGui.QImage.Format.Format_ARGB32)
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        grabbed = 0
        for screen in QtGui.QGuiApplication.screens():
            part = rect.intersected(screen.geometry())
            if part.isEmpty():
                continue
            geo = screen.geometry()
            one = screen.grabWindow(0, part.x() - geo.x(), part.y() - geo.y(),
                                    part.width(), part.height())
            if one.isNull() or one.width() == 0:
                continue
            painter.drawImage(part.x() - rect.x(), part.y() - rect.y(), one.toImage())
            grabbed += 1
        painter.end()
        if not grabbed:
            self._warn("这块没抓到东西，再框一次试试。")
            return
        shot = QtGui.QPixmap.fromImage(canvas)
        if shot.isNull() or shot.width() == 0 or shot.height() == 0:
            self._warn("这块没抓到东西，再框一次试试。")
            return
        image_path = self._shot_path()
        image_path.parent.mkdir(parents=True, exist_ok=True)
        # 先存新的、成功了再盖掉旧的 —— 以前是先删后存，存失败就连上一张都没了，
        # 界面还挂着旧缩略图、`_image_path` 指向一个已经不存在的文件。
        # `Path.replace` 是原子覆盖，盘上任何时候都只有一张 shot.png。
        tmp_path = image_path.with_name("shot_new.png")
        if not shot.save(str(tmp_path), "PNG"):
            self._warn("截图存不下来，再框一次试试。")
            return
        try:
            tmp_path.replace(image_path)
        except OSError as exc:
            self._warn(f"截图存不下来：{exc}，再框一次试试。")
            return
        self.bar.set_shot(str(image_path), shot)
        self.show_bar()

    # ---- 收尾 ----

    def _conn(self):
        """今天的库 —— 跨天了（过了零点）自动换到新一天那个文件夹。

        ⚠️ 别 close 旧连接：`record` 那边还握着同一个对象，跨零点时它要先
        `end_session(旧连接)` 收尾。这里只换引用，旧连接随 GC 自然收掉。
        """
        want = config.db_path()
        if self.conn is None or self._conn_path != want:
            self.conn = store.connect(want)
            self._conn_path = want
        return self.conn

    def _remember(self, record: dict) -> None:
        """答完记一笔：图问 / 文问分开，有图就先归档截图再落库（方便复盘）。"""
        if record.get("question", "").startswith("电脑助手："):
            steps = ops.parse_plan(record.get("answer") or "")
            if not steps:
                self.bar.append_text("（这没法变成具体操作 —— 上面的回复当普通回答看吧。"
                                     "试试更具体的说法，比如「把 D:/下载 里上周的 pdf 移到 D:/课件」）")
                return
            plan_text = NL.join(
                f"{i}. {ops.describe(step)}" for i, step in enumerate(steps, 1))
            self.bar.append_text("---- 计划预览 ----" + NL + plan_text + NL + "---- 等你确认 ----")
            box = QtWidgets.QMessageBox(self.bar)
            box.setWindowTitle("电脑助手 · 确认执行")
            box.setText(f"共 {len(steps)} 步，确认执行？" + NL + NL + plan_text + NL + NL
                        + "删除会进回收站；可反悔。")
            run_btn = box.addButton("执行", QtWidgets.QMessageBox.AcceptRole)
            box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(run_btn)
            box.exec()
            if box.clickedButton() is run_btn:
                self._execute_ops(steps)
            else:
                self.bar.append_text("（已取消，没有执行。）")
            return
        kind = "image" if record.get("kind") == "image" else "text"
        archived = ""
        if kind == "image":
            archived = self._archive_image(record.get("image_path") or "")
        try:
            ask_id = store.add_ask(
                self._conn(),
                record.get("question", ""),
                record.get("answer", ""),
                int(record.get("ms") or 0),
                config.ASK_API_MODEL or "codex",   # 真正答话的那个模型，别写死
                kind=kind,
                image_path=archived,
                thread=record.get("thread") or "",
            )
        except Exception as exc:
            print(f"写库失败：{exc}", file=sys.stderr)
            ask_id = 0
        if ask_id:
            self.bar.set_starrable(str(self._conn_path or config.db_path()), ask_id)
        self.bar.refresh_usage()         # 答案落库 ⇒ 占用数字跟着变

    def _archive_image(self, src: str) -> str:
        """把这轮用的截图拷进「问答截图」—— 原临时 shot.png 仍按需删，归档留下。"""
        if not src:
            return ""
        source = pathlib.Path(src)
        if not source.exists():
            return ""
        folder = config.ask_image_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = source.stat().st_mtime_ns
            dest = folder / f"ask_{stamp}.png"
            # 同名就加序号，绝不覆盖以前的
            n = 1
            while dest.exists():
                dest = folder / f"ask_{stamp}_{n}.png"
                n += 1
            shutil.copy2(source, dest)
            return str(dest)
        except Exception as exc:
            print(f"归档截图失败：{exc}", file=sys.stderr)
            return str(source)

    def _recent_asks(self):
        """给横栏「历史」按钮用：今天的问答（新→旧），带 kind / image_path / id。"""
        try:
            return store.recent_asks(self._conn(), limit=20)
        except Exception as exc:
            print(f"读历史失败：{exc}", file=sys.stderr)
            return []

    def _history_days(self):
        """更早有问答的日子（新→旧，最多 7 天）—— 历史菜单里「更早的日子」用。"""
        out = []
        today = config.day_dir()
        try:
            for day, db_path in study.day_dbs(config.DATA_ROOT):
                if db_path.parent == today:
                    continue                       # 今天那份走「历史」的主菜单
                conn = store.connect(db_path)
                try:
                    rows = store.recent_asks(conn, limit=20)
                finally:
                    conn.close()
                if rows:
                    out.append((f"{day.month}月{day.day}日", str(db_path), rows))
                if len(out) >= 7:
                    break
        except Exception as exc:
            print(f"读历史日子失败：{exc}", file=sys.stderr)
        return out

    # ---- 学习功能：复盘 / 上下文 / 收藏 / 专注统计 ----

    def _review_today(self) -> None:
        """「复盘」按钮：把今天的窗口记录 + 课堂转写交给 AI 总结。"""
        try:
            conn = self._conn()
            sessions = conn.execute(
                "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions ORDER BY id"
            ).fetchall()
            transcript_rows = store.search_transcripts(conn, limit=500)
        except Exception as exc:
            self._warn(f"读今天的记录失败：{exc}")
            return
        if not sessions and not transcript_rows:
            self._warn("今天还没有可复盘的记录 —— 先点托盘里的「开始记录」，下课再来点复盘。")
            return
        summary_lines = []
        for sid, started, ended in sessions:
            info = store.session_summary(conn, sid)
            line = f"{str(started)[11:16]} 起记了 {info.get('分钟', 0)} 分钟，切了 {info.get('切换', 0)} 次窗口"
            # 窗口标题是「在学什么」的最强信号 —— 把这次记录里看到的标题（去重，最多 8 个）带上
            seen: list[str] = []
            for _ts, _process, title in store.session_windows(conn, sid):
                t = (title or "").strip()
                if t and t not in seen:
                    seen.append(t)
                if len(seen) >= 8:
                    break
            if seen:
                line += "。看过：" + "；".join(seen)
            summary_lines.append(line)
        day = config.day_dir()
        frame_rows = store.frame_text_between(
            conn, f"{day.year:04d}-{day.month:02d}-{day.day:02d} 00:00:00",
            f"{day.year:04d}-{day.month:02d}-{day.day:02d} 23:59:59", limit=40)
        frame_text = chr(10).join(f"[{t[11:16]}] {x}" for _p, t, x in frame_rows)
        question = study.build_review_question(summary_lines,
                                               study.transcripts_digest(transcript_rows),
                                               frame_text)
        self.bar.ask_with_context(question, study.REVIEW_DISPLAY)

    def _transcript_context(self) -> str:
        """追问时捎带的课堂转写片段（最近这些年，cap 在 study 里控）。"""
        try:   # 刚录完也能带上 —— 有近 12 分钟内的转写就捎，没有就空串
            since = (datetime.datetime.now()
                     - datetime.timedelta(minutes=study._CONTEXT_MINUTES + 2)
                     ).strftime("%Y-%m-%d %H:%M:%S")
            rows = store.search_transcripts(self._conn(), ts_from=since, limit=100)
            return study.transcript_context(rows)
        except Exception:
            return ""                            # 上下文是锦上添花，坏了就纯问

    def _toggle_star(self, payload) -> None:
        """收藏 / 取消收藏：落回那条问答所在的库，然后让按钮文字跟真实状态走。"""
        try:
            db_path, ask_id = payload
            if self.conn is not None and str(db_path) == str(self._conn_path):
                conn = self.conn
                one_off = False
            else:
                conn = store.connect(db_path)    # 老日子的一次性连接
                one_off = True
            try:
                state = store.toggle_star(conn, int(ask_id))
            finally:
                if one_off:
                    conn.close()
            self.bar.set_star_label(state)
        except Exception as exc:
            self._warn(f"收藏没成功：{exc}")

    def _show_focus(self) -> None:
        """托盘「今天学了多久」：窗口记录算专注统计。"""
        try:
            line = study.focus_line(store.focus_stats(self._conn()))
        except Exception as exc:
            self._warn(f"统计没算出来：{exc}")
            return
        self.tray.showMessage("问一问 · 专注统计", line,
                              QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message(line)
        self.show_bar()

    def _export_anki(self) -> None:
        """托盘「导出错题本」：把所有日子里收藏的问答导成 Anki 能导入的 CSV。"""
        collected = []
        try:
            for day, db_path in study.day_dbs(config.DATA_ROOT):
                conn = store.connect(db_path)
                try:
                    collected.extend(store.starred_asks(conn))
                finally:
                    conn.close()
        except Exception as exc:
            self._warn(f"读收藏失败：{exc}")
            return
        if not collected:
            self._warn("错题本还是空的 —— 看历史时点「收藏」，想复习的题就攒下来了。")
            return
        dest = config.DATA_ROOT / f"错题本_{datetime.date.today():%Y%m%d}.csv"
        try:
            count = study.export_anki_csv(collected, dest)
        except Exception as exc:
            self._warn(f"导出失败：{exc}")
            return
        self._warn(f"导出 {count} 题到 {dest} —— Anki 里「文件→导入」选它就行。")

    # ---- 电脑助手：> 请求 → AI 出计划 → 预览确认 → 执行 ----

    def _computer_request(self, request: str) -> None:
        if not request:
            return
        if self.bar._worker is not None:
            self.bar.show_message("上一句还在写 —— 等它写完再叫电脑助手。")
            return
        plan_question = ops.plan_question(request)
        self.bar.ask_with_context(plan_question, f"电脑助手：{request}")

    def _execute_ops(self, steps: list[dict]) -> None:
        """后台线程逐步执行计划，结果一条条回流到答案区；全量写日志。"""
        import threading
        app_index = ops.start_menu_apps()
        log_lines = [f"--- {store.now()} ---"]

        def run() -> None:
            for i, step in enumerate(steps, 1):
                try:
                    if step.get("op") == "remind":
                        minutes = max(1, int(step.get("minutes") or 1))
                        msg = str(step.get("message") or "提醒")
                        self.bar.remind_scheduled.emit(minutes, msg)
                        result = f"✓ 已设提醒：{minutes} 分钟后 —— {msg}"
                    else:
                        result = "✓ " + ops.execute(step, app_index)
                except Exception as exc:
                    result = f"✗ 第 {i} 步失败：{exc}"
                log_lines.append(f"{i}. [{store.now()}] {ops.describe(step)} → {result}")
                self.bar.ops_result.emit(result)
            log_lines.append("")
            try:
                with open(config.day_dir() / "操作日志.txt", "a", encoding="utf-8") as f:
                    f.write("\n".join(log_lines) + "\n")
            except OSError:
                pass

        threading.Thread(target=run, name="ops-run", daemon=True).start()

    def _schedule_remind(self, minutes: int, message: str) -> None:
        self.scheduler.after(f"remind-{store.now()}", minutes * 60, message)

    def _scheduler_fired(self, name: str, payload) -> None:
        text = str(payload or "时间到。")
        if name.startswith("pomodoro"):
            text = "专注 25 分钟结束 —— 起来走两步，休息 5 分钟。"
            self.scheduler.after("pomodoro_break", 5 * 60, "休息结束 —— 继续加油！")
        self.tray.showMessage("问一问 · 提醒", text,
                              QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message("⏰ " + text)
        self.show_bar()

    def _start_pomodoro(self) -> None:
        self.scheduler.after("pomodoro", 25 * 60)
        self._warn("番茄钟开始了 —— 25 分钟后提醒你休息（这段时间适合开个录制）。")

    # ---- 学习产出：测验 / 报告 / 笔记 ----

    def _today_data(self):
        """把今天的录制/问答数据凑齐（给复盘/测验/报告共用）。"""
        conn = self._conn()
        sessions = conn.execute(
            "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions ORDER BY id").fetchall()
        transcript_rows = store.search_transcripts(conn, limit=500)
        asks = store.recent_asks(conn, limit=30)
        return sessions, transcript_rows, asks

    def _quiz_today(self) -> None:
        """「测验」：基于今天的记录出 5 道题，对话里逐题批改。"""
        sessions, transcript_rows, asks = self._today_data()
        if not sessions and not transcript_rows and not asks:
            self._warn("今天还没有可出题的素材 —— 先录一段课或问几个问题。")
            return
        summary_lines = []
        for sid, started, _ended in sessions:
            info = store.session_summary(conn, sid)
            summary_lines.append(
                f"{str(started)[11:16]} 起记了 {info.get('分钟', 0)} 分钟，切了 {info.get('切换', 0)} 次窗口")
        asks_preview = [f"问：{(r[1] or '')[:60]}" for r in asks[:10] if (r[1] or '').strip()]
        question = study.build_quiz_question(summary_lines, asks_preview,
                                             study.transcripts_digest(transcript_rows))
        self.bar.ask_with_context(question, "测验：来 5 道题考考我")

    def _generate_report(self) -> None:
        """生成今天的学习报告（Markdown，落当天文件夹）。AI 总结在后台线程补一段。"""
        import threading
        day = config.day_dir()
        sessions, transcript_rows, asks = self._today_data()
        starred = len(store.starred_asks(conn)) if (conn := self._conn()) else 0
        frames = len(list(liverec.frame_dir().glob("*.jpg")))
        summary_lines = []
        for sid, started, _ended in sessions:
            info = store.session_summary(conn, sid)
            line = f"- {str(started)[11:16]} 起记了 {info.get('分钟', 0)} 分钟，切了 {info.get('切换', 0)} 次窗口"
            top_name, top_min = info.get("最久") or ("", 0)
            if top_name and top_min:
                line += f"，最久停在「{top_name}」（{top_min} 分钟）"
            summary_lines.append(line)
        digest = study.transcripts_digest(transcript_rows)
        dest = day / f"学习报告_{day.name}.md"
        if not dest.exists():
            dest.write_text(study.build_daily_report(day.name, summary_lines, asks,
                                                     digest, starred, frames), encoding="utf-8")
        if not digest and not sessions:
            self._warn("今天还没有记录可写进报告。")
            return

        def ai_part() -> None:
            question = study.build_review_question(summary_lines, digest)
            try:
                ai = backend.ask(None, question, timeout=90)
                body = study.build_daily_report(day.name, summary_lines, asks,
                                                digest, starred, frames, ai_summary=ai)
                dest.write_text(body, encoding="utf-8")
            except Exception:
                return                  # AI 不在就保留纯数据版报告
            self.tray.showMessage("问一问", f"报告写好了（含 AI 要点）：{dest}",
                                  QtWidgets.QSystemTrayIcon.Information, 10000)

        threading.Thread(target=ai_part, name="report", daemon=True).start()
        self._warn(f"报告已生成：{dest}（AI 要点写完会自动补进去）")

    def _attach_doc(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self.bar, "选择要问的文档", "",
            "文档 (*.pdf *.docx *.pptx *.txt *.md);;所有文件 (*.*)")
        if not path:
            return
        try:
            text = study.extract_doc_text(path)
        except Exception as exc:
            self._warn(f"读文档失败：{exc}")
            return
        if len(text.strip()) < 20:
            self._warn("这份文档几乎没读到文字（扫描版 PDF 需要OCR，还不支持）。")
            return
        self.bar.set_doc(path, text)

    def _generate_glossary(self) -> None:
        """AI 从今天的转写+问答里提取学科术语，攒成术语表 Markdown。"""
        import threading
        _sessions, transcript_rows, asks = self._today_data()
        digest = study.transcripts_digest(transcript_rows)
        if not digest and not asks:
            self._warn("今天还没有转写和问答，攒不出术语表。")
            return
        asks_preview = [f"问：{(r[1] or '')[:60]}" for r in asks[:10] if (r[1] or '').strip()]
        question = study.build_glossary_question(digest, asks_preview)

        def run() -> None:
            try:
                terms = backend.ask(None, question, timeout=90)
            except Exception as exc:
                self.tray.showMessage("问一问", f"术语表没成：{exc}",
                                      QtWidgets.QSystemTrayIcon.Warning, 8000)
                return
            dest = config.day_dir() / "术语表.md"
            dest.write_text(f"# 术语表 · {config.day_dir().name}" + NL + NL + terms,
                            encoding="utf-8")
            self.tray.showMessage("问一问", f"术语表写好了：{dest}",
                                  QtWidgets.QSystemTrayIcon.Information, 10000)

        threading.Thread(target=run, name="glossary", daemon=True).start()

    def _export_notes(self) -> None:
        """导出今天的对话为 Markdown 笔记。"""
        asks = self._recent_asks()
        if not asks:
            self._warn("今天还没有问答可导出。")
            return
        day = config.day_dir()
        dest = day / f"对话笔记_{day.name}.md"
        count = study.export_day_notes_md(asks, dest, f"问一问对话笔记 · {day.name}")
        self._warn(f"导出 {count} 条问答到 {dest}")

    def _toggle_pause(self) -> None:
        if not self.live.recording:
            self._warn("现在没有在录制。")
            return
        self.live.set_paused(not self.live.paused)
        self.bar.set_rec_paused(self.live.paused)

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
                "问一问", f"自动备份完成：{result}（每周一次，可在 设置.json 里改 backup_dir 换地方）",
                QtWidgets.QSystemTrayIcon.Information, 8000)

    def _shot_path(self) -> pathlib.Path:
        return config.ask_tmp_dir() / "shot.png"

    def _shot_done(self) -> None:
        """临时截图收尾：只删「正在用的」shot.png；已归档进「问答截图」的不动（要复盘）。"""
        try:
            self._shot_path().unlink(missing_ok=True)
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
    app.aboutToQuit.connect(ask_app.bar.shutdown)   # 兜底：走别的路径退出也先收线程
    QtCore.QTimer.singleShot(0, ask_app.start)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
