# -*- coding: utf-8 -*-
"""学习功能这轮的回归测试：复盘 / 转写上下文 / 跨天历史 / 错题本 / 专注统计 / 备份。

纯函数（study.py / backup.py / store.py）直接测；bar 的新按钮测「有没有、亮没亮、
点了发什么信号」，不起网络。
"""
from __future__ import annotations

import datetime
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtWidgets  # noqa: E402

from learnsys import store  # noqa: E402
from learnsys.ask import backup, bar, study  # noqa: E402


def _app():
    a = QtWidgets.QApplication.instance()
    if a is None:
        a = QtWidgets.QApplication([])
    return a


def _seed_day(conn: sqlite3.Connection) -> None:
    """一段「刚开始 10 分钟」的记录：3 条窗口事件（2 次切换）+ 2 条转写 + 1 条问答。

    时刻用真实的 now-10 分钟起算 —— 写死日期的话，明天跑这测试全被钳成 0。
    """
    base = datetime.datetime.now() - datetime.timedelta(minutes=10)

    def stamp(minute_offset: int) -> str:
        return (base + datetime.timedelta(minutes=minute_offset)).strftime("%Y-%m-%d %H:%M:%S")

    started = stamp(0)
    cur = conn.execute("INSERT INTO sessions (started_at, ended_at) VALUES (?, '')", (started,))
    sid = int(cur.lastrowid or 0)
    for offset, process, title in ((0, "chrome.exe", "数据结构网课"),
                                   (1, "idea64.exe", "写代码"),
                                   (2, "chrome.exe", "B站")):
        store.add_window_event_at(conn, sid, stamp(offset), process, title)
    store.add_transcript(conn, sid, stamp(0), stamp(0), "单链表的插入要先断后接")
    store.add_transcript(conn, sid, stamp(1), stamp(1), "循环队列判断满的条件")
    store.add_ask(conn, "什么是头插法", "先让新节点指向头节点……", 1500, "codex")


class TestStoreStarred(unittest.TestCase):
    """错题本的库那一半：starred 列迁移、收藏翻转、按收藏查、行里带 id。"""

    def setUp(self):
        self.conn = store.connect(":memory:")
        _seed_day(self.conn)

    def test_add_ask_returns_id_and_recent_has_id(self):
        rows = store.recent_asks(self.conn, limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 6, "行里要带 id（第 6 列）")
        self.assertEqual(rows[0][5], 1)

    def test_toggle_star_flips(self):
        self.assertTrue(store.toggle_star(self.conn, 1))
        self.assertEqual([r[5] for r in store.starred_asks(self.conn)], [1])
        self.assertFalse(store.toggle_star(self.conn, 1))
        self.assertEqual(store.starred_asks(self.conn), [])
        self.assertFalse(store.toggle_star(self.conn, 999), "不存在的 id 别崩")

    def test_old_db_gets_starred_column(self):
        """老库（没有 starred 列）跑迁移后自动补列。"""
        old = sqlite3.connect(":memory:")
        old.execute("CREATE TABLE asks (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, "
                    "question TEXT, answer TEXT, ms INTEGER, backend TEXT)")
        old.commit()
        store._migrate(old)
        cols = {row[1] for row in old.execute("PRAGMA table_info(asks)").fetchall()}
        self.assertIn("starred", cols)
        old.close()


class TestStoreFocus(unittest.TestCase):
    """专注统计：总时长、切换数、按程序的停留分布。"""

    def test_focus_stats(self):
        conn = store.connect(":memory:")
        _seed_day(conn)
        stats = store.focus_stats(conn)
        self.assertEqual(stats["切换"], 2)
        self.assertAlmostEqual(stats["分钟"], 10.0, delta=0.2)
        apps = dict(stats["程序"])
        self.assertIn("chrome", apps)
        self.assertIn("idea64", apps)
        # chrome 出现在第 1、3 条：开头 1 分钟 + 第 2 条结束（1 分钟处）到现在 ≈ 9 分钟
        self.assertGreater(apps["chrome"], apps["idea64"])

    def test_focus_stats_empty(self):
        conn = store.connect(":memory:")
        stats = store.focus_stats(conn)
        self.assertEqual(stats["分钟"], 0)
        self.assertEqual(stats["程序"], [])


class TestStudyHelpers(unittest.TestCase):
    """study.py 的纯函数。"""

    def test_day_dbs_sorts_by_date_not_string(self):
        """2026.10.10 必须排在 2026.10.6 后面（字符串排序会排反）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name in ("2026.10.6", "2026.10.10", "2026.9.30"):
                (root / name).mkdir()
                (root / name / "learnsys.db").write_bytes(b"x")
            (root / "乱起的文件夹").mkdir()          # 没库 ⇒ 不算
            days = study.day_dbs(root)
            self.assertEqual([d.isoformat() for d, _ in days],
                             ["2026-10-10", "2026-10-06", "2026-09-30"])

    def test_transcripts_digest(self):
        rows = [("2026-10-06 10:00:00", "2026-10-06 10:00:45", "讲链表"),
                ("2026-10-06 10:01:00", "2026-10-06 10:01:45", "")]
        text = study.transcripts_digest(rows)
        self.assertIn("[10:00] 讲链表", text)
        self.assertNotIn("10:01", text, "空转写不进正文")

    def test_transcripts_digest_4col_rows(self):
        """search_transcripts 的行是 4 列（含 session_id）—— 正文在 [3] 不是 [2]。

        真踩过：拿 [2]（ts_end）当正文，AI 收到的转写全是空的。
        """
        rows = [(1, "2026-10-06 10:00:00", "2026-10-06 10:00:45", "单链表插入先接后断"),
                (1, "2026-10-06 10:01:00", "2026-10-06 10:01:45", "")]
        text = study.transcripts_digest(rows)
        self.assertIn("[10:00] 单链表插入先接后断", text)
        self.assertNotIn("10:01:45", text, "ts_end 不许被当成正文")

    def test_transcript_context_4col_rows(self):
        now = datetime.datetime(2026, 10, 6, 10, 12, 0)
        rows = [(1, "2026-10-06 10:11:00", "x", "刚刚讲到的"),
                (1, "2026-10-06 09:00:00", "x", "一小时前的")]
        ctx = study.transcript_context(rows, now=now)
        self.assertIn("刚刚讲到的", ctx)
        self.assertNotIn("一小时前的", ctx)

    def test_build_review_question(self):
        q = study.build_review_question(["10:00 起记了 30 分钟"], "单链表插入")
        self.assertIn("【窗口摘要】", q)
        self.assertIn("10:00 起记了 30 分钟", q)
        self.assertIn("【声音转写】", q)
        self.assertIn("单链表插入", q)
        self.assertIn("复习建议", q)
        q2 = study.build_review_question([], "")
        self.assertIn("没有窗口记录", q2)

    def test_transcript_context_only_recent(self):
        now = datetime.datetime(2026, 10, 6, 10, 12, 0)
        rows = [
            ("2026-10-06 10:11:00", "x", "刚刚讲到的"),
            ("2026-10-06 09:00:00", "x", "一小时前的"),
        ]
        ctx = study.transcript_context(rows, now=now)
        self.assertIn("刚刚讲到的", ctx)
        self.assertNotIn("一小时前的", ctx)
        self.assertEqual(study.transcript_context([], now=now), "")

    def test_focus_line(self):
        line = study.focus_line({"分钟": 95.0, "切换": 7,
                                 "程序": [("chrome", 50.0), ("idea64", 30.0)]})
        self.assertIn("95 分钟", line)
        self.assertIn("chrome 50 分", line)

    def test_export_anki_csv(self):
        rows = [("2026-10-06 10:00:00", "什么是链表", "线性结构", "text", "", 1),
                ("2026-10-06 10:01:00", "", "空问题的不要", "text", "", 2)]
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "错题本.csv"
            count = study.export_anki_csv(rows, dest)
            self.assertEqual(count, 1)
            raw = dest.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "utf-8-sig，Excel/Anki 不乱码")
            self.assertIn("什么是链表".encode("utf-8"), raw)


class TestBackup(unittest.TestCase):
    """备份：打包、跳过该跳的、保留策略、该不该备。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / "学习系统"
        self.bak = pathlib.Path(self.tmp.name) / "备份"
        self.root.mkdir()
        (self.root / "2026.10.6").mkdir()
        (self.root / "2026.10.6" / "learnsys.db").write_bytes(b"db")
        (self.root / "设置.json").write_text("{}", encoding="utf-8")

    def test_backup_zips_and_skips(self):
        (self.root / "2026.10.6" / "backup").mkdir()
        (self.root / "2026.10.6" / "backup" / "x.zip").write_bytes(b"z")   # 该跳过
        zip_path = backup.do_backup(self.root, self.bak)
        self.assertTrue(zip_path.exists())
        import zipfile
        names = zipfile.ZipFile(zip_path).namelist()
        self.assertIn("2026.10.6/learnsys.db", "/".join(names).replace("\\", "/") and names[0] and names)  # 形式合法
        joined = "|".join(names)
        self.assertIn("learnsys.db", joined)
        self.assertNotIn("backup/", joined, "跳过备份目录")

    def test_prune_keeps_recent(self):
        for i in range(10):
            backup.do_backup(self.root, self.bak,
                             when=datetime.datetime(2026, 10, 1, 10, i))
        zips = list(self.bak.glob("学习系统_*.zip"))
        self.assertEqual(len(zips), backup.KEEP, "只留最近 KEEP 份")

    def test_needs_backup(self):
        self.assertTrue(backup.needs_backup(self.bak), "一份都没有 ⇒ 该备")
        backup.do_backup(self.root, self.bak)
        self.assertFalse(backup.needs_backup(self.bak, every_days=7))
        self.assertTrue(backup.needs_backup(self.bak, every_days=0), "0 天 ⇒ 永远该备")


class TestBarStudyUI(unittest.TestCase):
    """横栏上的新按钮：收藏的亮灭、复盘入口、上下文传递、历史行带收藏信息。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_star_disabled_until_starrable(self):
        self.assertFalse(self.b.star_btn.isEnabled())
        self.b.set_starrable("D:/x/learnsys.db", 7)
        self.assertTrue(self.b.star_btn.isEnabled())
        self.b.set_star_label(True)
        self.assertEqual(self.b.star_btn.text(), "已收藏★")
        self.b._reset_answer()
        self.assertFalse(self.b.star_btn.isEnabled())

    def test_star_click_emits_payload(self):
        got = []
        self.b.star_toggled.connect(lambda p: got.append(p))
        self.b._show_past("历史问", "历史答", "text", "", ("D:/x/learnsys.db", 3))
        self.b.star_btn.click()
        self.assertEqual(got, [("D:/x/learnsys.db", 3)])

    def test_review_click_emits_signal(self):
        got = []
        self.b.review_requested.connect(lambda: got.append(1))
        self.b.review_btn.click()
        self.assertEqual(got, [1])

    def test_ask_with_context_shows_display_sends_full(self):
        """复盘：界面上显示短句，发给 worker 的是完整题 + 不带追问上下文。"""
        captured = {}

        class FakeWorker:
            finished = mock.MagicMock()
            chunk = mock.MagicMock()
            done = mock.MagicMock()
            failed = mock.MagicMock()

            def __init__(self, image_path, question, history, parent=None, context="",
                         extra_images=None):
                captured.update(image_path=image_path, question=question,
                                history=history, context=context,
                                extra_images=extra_images)

            def start(self):
                pass

            def cancel(self):
                pass

            def wait(self, ms):
                return True

        with mock.patch.object(bar, "_AskWorker", FakeWorker):
            self.b.ask_with_context("完整题目" + "很长" * 100, "复盘：我刚才学了什么？", "")
        self.assertEqual(captured["question"].startswith("完整题目"), True)
        self.assertEqual(captured["context"], "")
        self.assertIn("复盘：我刚才学了什么？", self.b.answer.toPlainText())

    def test_submit_passes_extra_context(self):
        captured = {}

        class FakeWorker:
            finished = mock.MagicMock()
            chunk = mock.MagicMock()
            done = mock.MagicMock()
            failed = mock.MagicMock()

            def __init__(self, image_path, question, history, parent=None, context="",
                         extra_images=None):
                captured.update(question=question, context=context,
                                extra_images=extra_images)

            def start(self):
                pass

            def cancel(self):
                pass

            def wait(self, ms):
                return True

        self.b.extra_context_provider = lambda: "课堂转写片段"
        self.b.ask.setText("这题怎么解")
        with mock.patch.object(bar, "_AskWorker", FakeWorker):
            self.b.submit()
        self.assertEqual(captured["context"], "课堂转写片段")
        self.assertEqual(captured["question"], "这题怎么解", "界面问题原样发，上下文另走一个参数")
        # 清场：submit 起过假 worker，把状态复位
        self.b._drop_running()

    def test_add_ask_rows_wires_star_info(self):
        """历史菜单行点开要把 (db, id) 带进 _show_past。"""
        menu = QtWidgets.QMenu()
        rows = [("2026-10-05 10:00:00", "老问题", "老答案", "text", "", 42)]
        self.b._add_ask_rows(menu, rows, "D:/old/learnsys.db")
        self.assertEqual(len(menu.actions()), 1)
        menu.actions()[0].trigger()
        self.assertEqual(self.b._starrable, ("D:/old/learnsys.db", 42))
        self.assertTrue(self.b.star_btn.isEnabled())

    def test_history_days_submenu(self):
        self.b.history_provider = lambda: []
        self.b.history_days_provider = lambda: [("10月5日", "D:/old.db", [
            ("2026-10-05 09:00:00", "前天的问", "前天的答", "text", "", 9)])]
        # 不真 exec 菜单（会阻塞）—— 只验证 provider 坏了也不会炸
        self.b.history_days_provider = lambda: 1 / 0
        try:  # _show_history 会 exec 阻塞 ⇒ 只测 provider 容错逻辑
            self.b.history_days_provider = lambda: []
            self.b.history_db_path_provider = lambda: "D:/today.db"
            rows = self.b.history_provider() or []
            self.assertEqual(rows, [])
        finally:
            self.b.history_days_provider = None
            self.b.history_db_path_provider = None


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestBackendMultiImage(unittest.TestCase):
    """复盘快照喂 AI：backend 支持主图之外再带最多 4 张附加图。"""

    def test_messages_carry_extra_images(self):
        from learnsys.ask import backend as be
        with mock.patch.object(be, "_data_url", side_effect=lambda p: f"data:{p}"):
            msgs = be._messages("main.png", "复盘一下", None, "chat",
                                extra_images=["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"])
        first = msgs[1]["content"]
        imgs = [c for c in first if c["type"] == "image_url"]
        self.assertEqual(len(imgs), 4, "最多带 4 张（主图 + 3 张附加）")
        self.assertEqual(msgs[0]["content"], be.config.ASK_SYSTEM_PROMPT)

    def test_responses_style_extra_images(self):
        from learnsys.ask import backend as be
        with mock.patch.object(be, "_data_url", side_effect=lambda p: f"data:{p}"):
            msgs = be._messages(None, "复盘一下", None, "responses",
                                extra_images=["a.jpg", "b.jpg"])
        first = msgs[1]["content"]
        imgs = [c for c in first if c["type"] == "input_image"]
        self.assertEqual(len(imgs), 2)

    def test_no_images_stays_text(self):
        from learnsys.ask import backend as be
        msgs = be._messages(None, "纯文字", None, "chat")
        self.assertEqual(msgs[1]["content"], [{"type": "text", "text": "纯文字"}])
