"""学习产出：今日素材、测验、学习报告、术语表、附件、对话笔记。"""
from __future__ import annotations

import datetime
import threading

from PySide6 import QtWidgets

from learnsys import config, product, store
from . import NL
from learnsys.ask import backend, liverec, study


class StudyOpsMixin:
    # ---- 学习产出：测验 / 报告 / 笔记 ----

    def _today_data(self):
        """把今天的录制/问答数据凑齐（给复盘/测验/报告共用）。

        统一库下必须按日期过滤，否则会把历史全算进「今天」。
        """
        conn = self._conn()
        day_text = datetime.date.today().isoformat()
        sessions = conn.execute(
            "SELECT id, started_at, COALESCE(ended_at, '') FROM sessions "
            "WHERE started_at LIKE ? ORDER BY id", (f"{day_text}%",)).fetchall()
        transcript_rows = store.search_transcripts(
            conn, ts_from=f"{day_text} 00:00:00", ts_to=f"{day_text} 23:59:59",
            limit=500)
        asks = store.recent_asks(conn, limit=30, day=day_text)
        return sessions, transcript_rows, asks

    def _quiz_today(self) -> None:
        """「测验」：基于今天的记录出 5 道题，对话里逐题批改。"""
        sessions, transcript_rows, asks = self._today_data()
        if not sessions and not transcript_rows and not asks:
            self._warn("今天还没有可出题的素材 —— 先录一段课或问几个问题。")
            return
        summary_lines = []
        conn = self._conn()
        for sid, started, _ended in sessions:
            info = store.session_summary(conn, sid)
            summary_lines.append(
                f"{str(started)[11:16]} 起记了 {info.get('分钟', 0)} 分钟，切了 {info.get('切换', 0)} 次窗口")
        asks_preview = [f"问：{(r[1] or '')[:60]}" for r in asks[:10] if (r[1] or '').strip()]
        question = study.build_quiz_question(summary_lines, asks_preview,
                                             study.transcripts_digest(transcript_rows))
        self.bar.quiz_mode = True          # 作答那几轮也保持测验模式，判错才能自动收题
        self.bar.ask_with_context(question, "测验：来 5 道题考考我", mode="quiz")

    def _generate_report(self) -> None:
        """生成今天的学习报告（Markdown，落当天文件夹）。AI 总结在后台线程补一段。"""
        import threading
        day = config.day_dir()
        sessions, transcript_rows, asks = self._today_data()
        conn = self._conn()
        starred = (store.wrong_counts(conn, datetime.date.today())["new_today"]
                   if conn else 0)
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
            self.tray.showMessage(product.PRODUCT_NAME, f"报告写好了（含 AI 要点）：{dest}",
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
                self.tray.showMessage(product.PRODUCT_NAME, f"术语表没成：{exc}",
                                      QtWidgets.QSystemTrayIcon.Warning, 8000)
                return
            dest = config.day_dir() / "术语表.md"
            dest.write_text(f"# 术语表 · {config.day_dir().name}" + NL + NL + terms,
                            encoding="utf-8")
            self.tray.showMessage(product.PRODUCT_NAME, f"术语表写好了：{dest}",
                                  QtWidgets.QSystemTrayIcon.Information, 10000)

        threading.Thread(target=run, name="glossary", daemon=True).start()

    def _export_notes(self) -> None:
        """导出今天的对话为 Markdown 笔记。"""
        try:
            asks = store.recent_asks(self._conn(), limit=200,
                                     day=datetime.date.today().isoformat())
        except Exception as exc:
            self._warn(f"读今天的问答失败：{exc}")
            return
        if not asks:
            self._warn("今天还没有问答可导出。")
            return
        day = config.day_dir()
        dest = day / f"对话笔记_{day.name}.md"
        count = study.export_day_notes_md(asks, dest, f"问一问对话笔记 · {day.name}")
        self._warn(f"导出 {count} 条问答到 {dest}")
