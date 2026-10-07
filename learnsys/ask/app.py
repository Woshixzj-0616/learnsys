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
from learnsys.ask import identity, overlay, single

LAUNCHER_NAME = "问一问.cmd"      # 源码运行时那个启动器：开机自启、开始菜单快捷方式都指向它


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
        self.bar.extra_context_provider = self._transcript_context
        self.bar.history_provider = self._recent_asks
        self.bar.history_days_provider = self._history_days
        self.bar.history_db_path_provider = lambda: str(self._conn_path or config.db_path())
        self._backup_worker = None
        self._backup_dir = (pathlib.Path(config.USER.get("backup_dir"))
                            if config.USER.get("backup_dir")
                            else config.DATA_ROOT.parent / "学习系统备份")
        self.recorder = record.WindowRecorder(self._conn)   # 采集层：记「你在看哪个窗口」
        self.recorder.ticked.connect(self._record_tick)
        self.caller = single.Server(self)      # 别人再点一次 → 把横栏叫回来（不再开第二个）
        self.caller.called.connect(self._called_back)
        self.tray = self._build_tray()

    # ---- 托盘 ----

    def _build_tray(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(_tray_icon(), self)
        menu = QtWidgets.QMenu()
        menu.addAction(f"框选提问（{self.hotkey.pretty}）", self.pick)
        menu.addSeparator()
        self.record_action = menu.addAction("开始记录（记我在看什么）")
        self.record_action.setCheckable(True)
        self.record_action.triggered.connect(self._toggle_record)
        menu.addAction("展开横栏", self.show_bar)
        menu.addAction("收起成小条", lambda: self.bar.set_collapsed(True))
        menu.addAction("回到屏幕上方居中", self.bar.center_top)
        menu.addAction("打开今天的数据文件夹", self.open_today)
        menu.addAction("今天学了多久（专注统计）", self._show_focus)
        menu.addAction("导出错题本（Anki CSV）", self._export_anki)
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
        self._maybe_auto_backup()           # 距上次备份超一周就在后台打一份
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

    # ---- 采集层：开始 / 结束记录 ----

    def _toggle_record(self, checked: bool) -> None:
        if checked:
            self.recorder.start()
            self.tray.showMessage(
                "问一问", "开始记录了 —— 你在看哪个窗口会被记下来，**只记到你喊停为止**，不全天。",
                QtWidgets.QSystemTrayIcon.Information, 6000)
        else:
            done = self.recorder.stop()
            self.tray.showMessage("问一问", self._record_summary(done),
                                  QtWidgets.QSystemTrayIcon.Information, 10000)
        self._sync_record_ui()

    def _record_summary(self, done: dict) -> str:
        """结束时那句话：记了多久、切了几次、最久停在哪个程序。"""
        if not done:
            return "这段没记下东西。"
        top_name, top_min = done.get("最久") or ("", 0)
        text = f"记完了：{done.get('分钟', 0)} 分钟 · 切了 {done.get('切换', 0)} 次窗口"
        if top_name and top_min:
            text += f" · 最久停在「{top_name}」约 {top_min} 分钟"
        text += f"。\n在 {config.day_dir()} 里。"
        return text

    def _sync_record_ui(self) -> None:
        """托盘那条菜单 + 横栏那行字，跟着记录状态走。"""
        on = self.recorder.running
        self.record_action.setChecked(on)
        self._record_tick()

    def _record_tick(self) -> None:
        """每秒：菜单上显示记了多久，横栏上显示「记录中」。"""
        on = self.recorder.running
        if on:
            self.record_action.setText(
                f"结束记录（已记 {self.recorder.elapsed:.0f} 分钟 · 切 {self.recorder.switches} 次）")
        else:
            self.record_action.setText("开始记录（记我在看什么）")
        self.bar.set_recording(on, self.recorder.elapsed, self.recorder.switches)

    def quit(self) -> None:
        self.bar.shutdown()      # 先把问答线程收干净 —— 还在跑就销毁会崩（QThread）
        if self._backup_worker is not None and self._backup_worker.isRunning():
            self._backup_worker.wait(30000)     # 打包到一半别留半个 zip（数据不大，等得起）
        if self.recorder is not None and self.recorder.running:
            self.recorder.stop()      # 退出前把这段记录收尾，别留个没结束的 session
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
        question = study.build_review_question(summary_lines,
                                               study.transcripts_digest(transcript_rows))
        self.bar.ask_with_context(question, study.REVIEW_DISPLAY)

    def _transcript_context(self) -> str:
        """追问时捎带的课堂转写片段（最近这些年，cap 在 study 里控）。"""
        if self.recorder is None or not self.recorder.running:
            return ""
        try:
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

    # ---- 数据备份 ----

    def _backup_now(self) -> None:
        self._run_backup(manual=True)

    def _maybe_auto_backup(self) -> None:
        if backup.needs_backup(self._backup_dir):
            self._run_backup(manual=False)

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
