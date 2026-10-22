"""学习工作台 · 入口：托盘 + 全局热键 + 框选 + 顶部横栏（问答部分叫「问一问」）。

双击「学习工作台.cmd」让它常驻：启动就在屏幕上方出一条横栏（上面写着本程序占了多少盘），
按 Alt+Q（或点横栏上的「框选」）框一块屏幕，就在那条横栏里问它。
数据存在 D 盘专用文件夹里、按天分：D:\学习系统6.10.2\（那天的库 + 那天的截图）；**打开 app 就先把当天的文件夹建出来**。

本文件只留：AskApp 的生命周期、框选截图、入口 main。
托盘 / 服务 / 会话 / 学习产出 / 备份分别在 `learnsys/ask/desktop/` 下。
"""
from __future__ import annotations

import pathlib
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from learnsys import config, product, store
from learnsys.ask import bar, guard, hotkey as hotkey_mod, liverec, ocr, overlay, scheduler, single
from .desktop.assistant_ops import AssistantOpsMixin
from .desktop.data_backup import DataBackupMixin
from .desktop.sessions import SessionsMixin
from .desktop.startup import _StartupWorker
from .desktop.study_ops import StudyOpsMixin
from .desktop.tray import TrayMixin
from .desktop.web_service import (WebServiceMixin, _server_healthy,
                                  _silence_windowed, newest_source_mtime,
                                  version_line)



class AskApp(TrayMixin, WebServiceMixin, SessionsMixin, AssistantOpsMixin,
             StudyOpsMixin, DataBackupMixin, QtCore.QObject):
    # 框选松手后有 140ms 的截图延迟 —— 这期间再按快捷键不许框出第二个。
    # 放类上：谁都有默认值，别依赖 __init__ 跑过（测试里有 __new__ 裸构造的用法）
    _capture_scheduled = False
    # Web 工作台的请求从 FastAPI 线程发出来 → 发信号排队回 Qt 主线程
    show_bar_requested = QtCore.Signal()
    pick_requested_ui = QtCore.Signal()

    def __init__(self, app: QtWidgets.QApplication, background: bool = False):
        super().__init__()
        self.app = app
        self.background = background        # --background：只起后台/横栏/托盘，不自动弹网页
        self.show_bar_requested.connect(self.show_bar)
        self.pick_requested_ui.connect(self.pick)
        try:
            from learnsys.server import runtime as web_runtime
            web_runtime.register_ui(show_bar=self.show_bar_requested.emit,
                                    pick=self.pick_requested_ui.emit)
        except Exception as exc:
            print(f"工作台↔快捷栏桥没接上：{exc}", file=sys.stderr)
        self.conn = None
        self._conn_path = None
        self.snip = None
        self.hotkey = hotkey_mod.GlobalHotkey(config.ASK_HOTKEY)
        self.hotkey.triggered.connect(self.pick)
        self.hotkey.failed.connect(self._warn)
        self.bar = bar.AskBar(self.hotkey.pretty)     # 全程序唯一一条横栏
        self.bar.pick_requested.connect(self.pick)
        self.bar.answered.connect(self._remember)
        self.bar.workbench_requested.connect(self.open_web)
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
        self._web_server = None                  # FastAPI/uvicorn 后台线程（P2）
        self._web_port = 0                       # 8765，占了就退 8766
        self._web_external = False               # 复用已在跑的后台，不归本进程管
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

    def start(self) -> None:
        day = self.prepare_today()          # 打开 app 就先把当天的文件夹建出来
        self._install_shortcuts()           # 开始菜单入口 + 清旧版残留
        ready = self.hotkey.register()      # 快捷键被占了也别把界面藏起来
        self.show_bar()
        message = f"{product.PRODUCT_NAME} {version_line()} ｜ 今天的数据放这儿：{day}"
        if self._exe_is_stale():
            # 「学习工作台.cmd」优先启动 dist 里的 exe —— 源码改了没重新打包时，
            # 跑的还是旧版，测试结果会让人怀疑人生（真踩过）
            message += "\n⚠️ 源码比 exe 新 —— 现在跑的还是旧版，双击 打包.cmd 重新打包再测。"
        self.bar.show_message(message)
        self._startup_worker = _StartupWorker(config.DATA_ROOT, self._backup_dir, self)
        self._startup_worker.message.connect(
            lambda m: self.tray.showMessage(product.PRODUCT_NAME, m,
                                            QtWidgets.QSystemTrayIcon.Information, 10000))
        self._startup_worker.start()        # 备份/清理/查新版本都在后台
        if ready and not self.background:
            self.tray.showMessage(
                product.PRODUCT_NAME,
                f"已就绪 —— 按 {self.hotkey.pretty} 框一块屏幕；横栏能拖着挪、也能收成小条。",
                QtWidgets.QSystemTrayIcon.Information, 5000)
        # --background 只抑制网页窗口；后台、横栏、托盘照常
        if config.WORKBENCH_ON_START and not self.background:
            # 等后台线程把 8765/8766 绑定好再开窗；页面自己也有重试，早了也不白屏
            QtCore.QTimer.singleShot(700, self.open_web)

    def _exe_is_stale(self) -> bool:
        """打包出的 exe 是不是比仓库源码旧（只在「exe 就在仓库 dist 里」时才比得出）。"""
        if not config.FROZEN:
            return False
        src_dir = config.ROOT.parent.parent / "learnsys"   # exe 在 dist/学习工作台/ 下
        newest = newest_source_mtime(src_dir)
        if newest is None:
            return False
        try:
            exe_mtime = pathlib.Path(sys.executable).stat().st_mtime
        except OSError:
            return False
        return newest > exe_mtime + 60      # 放 60 秒余量，打包尾动不动几秒

    def quit(self) -> None:
        guard.mark_quit()        # 告诉后台守护：这次是用户自己关的，别自动拉回来
        try:
            from learnsys.server import runtime as web_runtime
            web_runtime.clear_ui()   # 退出后别再让页面点「快捷栏」打到空处
        except Exception:
            pass
        self._ocr.shutdown()     # OCR 线程先停：别让它在关库之后还写 frame_text
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
        if self._web_server is not None:
            try:
                self._web_server.should_exit = True
            except Exception:
                pass
        self.app.quit()

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
        # 不 hide() 横栏：遮罩会用不透明块把横栏整块盖住（截图抓不到），
        # 这样任务栏不闪、焦点不丢，取消后也不用再抢一次焦点。
        self.snip = overlay.Overlay(cover=[self.bar.frameGeometry()])
        self.snip.selected.connect(self._region_chosen)
        self.snip.cancelled.connect(self._pick_cancelled)
        self.snip.show()

    def _pick_cancelled(self) -> None:
        self.snip = None
        self.show_bar()                  # 框选取消 → 横栏原样回来
        self.bar.activateWindow()

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

    def _shot_path(self) -> pathlib.Path:
        return config.ask_tmp_dir() / "shot.png"

    def _shot_done(self) -> None:
        """临时截图收尾：只删「正在用的」shot.png；已归档进「问答截图」的不动（要复盘）。"""
        try:
            self._shot_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _warn(self, message: str) -> None:
        self.tray.showMessage(product.PRODUCT_NAME, message, QtWidgets.QSystemTrayIcon.Warning, 6000)
        self.bar.show_message(message)
        self.show_bar()


def main() -> int:
    _silence_windowed()                   # 无黑框模式：print 不能炸
    argv = sys.argv[1:]
    background = "--background" in argv   # 开机自启：只起后台/横栏，不弹工作台
    if "--watchdog" in argv:
        # 计划任务每分钟来一次。用户手动退出过、或后台还活着 → 当场走人；
        # 先判断再建 Qt，闲着的时候只花一次健康探测的钱。
        if not guard.should_start(quit_requested=guard.quit_requested(),
                                  healthy=_server_healthy(8765) or _server_healthy(8766)):
            return 0
        background = True                 # 被守护拉起时别抢焦点
    else:
        guard.clear_quit()                # 任何正常启动都代表「这次我想让它跑」
    app = QtWidgets.QApplication(sys.argv)
    if not single.claim("background" if background else "show"):
        return 0                          # 已经有实例在跑 → 通知它后自己退
    app.setApplicationName("learnsys-ask")
    app.setQuitOnLastWindowClosed(False)
    ask_app = AskApp(app, background=background)
    ask_app.start_web()                 # 本地服务与快捷栏同一个进程
    app.aboutToQuit.connect(ask_app.hotkey.unregister)
    app.aboutToQuit.connect(ask_app.bar.shutdown)   # 兜底：走别的路径退出也先收线程
    QtCore.QTimer.singleShot(0, ask_app.start)
    return app.exec()
