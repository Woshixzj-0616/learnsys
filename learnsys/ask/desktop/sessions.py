"""录制与会话：记录开关、问答落库、历史、收藏、专注、导出。"""
from __future__ import annotations

import datetime
import pathlib
import shutil
import sys

from PySide6 import QtWidgets

from learnsys import config, product, store
from . import NL
from learnsys.ask import study
from learnsys.services import ops



class SessionsMixin:
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
        self.tray.showMessage(product.PRODUCT_NAME, text, QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message(text.replace(chr(10), " "))
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
        """更早有问答的日子（新→旧，最多 7 天）—— 历史菜单里「更早的日子」用。

        v2 统一库把所有日子放在一起，「更早的日子」会重复；主「历史」列表已经
        按时间倒序包含全部，所以这里直接返回空。
        """
        if config.UNIFIED_DB:
            return []
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
    def _review_today(self) -> None:
        """「复盘」按钮：把今天的窗口记录 + 课堂转写交给 AI 总结。"""
        try:
            conn = self._conn()
            day_text = datetime.date.today().isoformat()
            sessions = conn.execute(
                "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions "
                "WHERE started_at LIKE ? ORDER BY id", (f"{day_text}%",)
            ).fetchall()
            transcript_rows = store.search_transcripts(
                conn, ts_from=f"{day_text} 00:00:00", ts_to=f"{day_text} 23:59:59",
                limit=500)
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
        """收藏 / 取消收藏 = 收进 / 移出统一错题本。"""
        try:
            db_path, ask_id = payload
            if config.UNIFIED_DB:
                db_path = config.db_path()       # 统一库下不认历史菜单里的旧路径
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
            line = study.focus_line(store.focus_stats(
                self._conn(), day=datetime.date.today().isoformat()))
        except Exception as exc:
            self._warn(f"统计没算出来：{exc}")
            return
        self.tray.showMessage(f"{product.PRODUCT_NAME} · 专注统计", line,
                              QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message(line)
        self.show_bar()

    def _export_anki(self) -> None:
        """托盘「导出错题本」：把统一错题本导成 Anki 能导入的 CSV。"""
        collected = []
        try:
            for _day, db_path in study.storage_dbs(config.DATA_ROOT):
                conn = store.connect(db_path)
                try:
                    collected.extend(store.wrong_items(conn, status="all", limit=1000))
                finally:
                    conn.close()
        except Exception as exc:
            self._warn(f"读错题本失败：{exc}")
            return
        if not collected:
            self._warn("错题本还是空的 —— 测验答错会自动收进来，也可以在看历史时点「收藏」。")
            return
        dest = config.DATA_ROOT / f"错题本_{datetime.date.today():%Y%m%d}.csv"
        try:
            count = study.export_wrongbook_csv(collected, dest)
        except Exception as exc:
            self._warn(f"导出失败：{exc}")
            return
        self._warn(f"导出 {count} 题到 {dest} —— Anki 里「文件→导入」选它就行。")
    def _toggle_pause(self) -> None:
        if not self.live.recording:
            self._warn("现在没有在录制。")
            return
        self.live.set_paused(not self.live.paused)
        self.bar.set_rec_paused(self.live.paused)
