# -*- coding: utf-8 -*-
"""电脑助手 / 定时框架 / 文档问答 / OCR / 复习提醒 的回归测试。

外部副作用全部 mock（回收站、OCR 引擎、AI），文件操作在临时目录。
"""
from __future__ import annotations

import datetime
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from learnsys import store  # noqa: E402
from learnsys.ask import bar, liverec, ops, scheduler, study  # noqa: E402


def _app():
    a = QtWidgets.QApplication.instance()
    if a is None:
        a = QtWidgets.QApplication([])
    return a


def _wait(fn, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QtWidgets.QApplication.processEvents()
        if fn():
            return True
        time.sleep(0.02)
    return False


class TestOpsParseValidate(unittest.TestCase):
    """计划解析与安全校验 —— 电脑助手的安全闸门。"""

    def test_parse_plan_from_fenced_json(self):
        text = "好的，计划如下：\n```json\n[{\"op\": \"mkdir\", \"path\": \"D:/a\"}]\n```"
        self.assertEqual(ops.parse_plan(text), [{"op": "mkdir", "path": "D:/a"}])

    def test_parse_plan_invalid_returns_empty(self):
        self.assertEqual(ops.parse_plan("我觉得你还是手动整理比较好。"), [])
        self.assertEqual(ops.parse_plan("[{broken"), [])

    def test_validate_rejects_unknown_and_missing(self):
        ok, err = ops.validate({"op": "format_c"})
        self.assertFalse(ok)
        ok, err = ops.validate({"op": "mkdir"})
        self.assertFalse(ok)
        self.assertIn("path", err)

    def test_validate_rejects_protected_paths(self):
        ok, err = ops.validate({"op": "delete", "path": "C:/Windows/System32/cmd.exe"})
        self.assertFalse(ok)
        self.assertIn("拒绝", err)
        ok, _ = ops.validate({"op": "move", "src": "D:/a.txt", "dst_dir": "C:/Program Files/x"})
        self.assertFalse(ok)

    def test_validate_rename_bad_name(self):
        ok, _ = ops.validate({"op": "rename", "path": "D:/a.txt", "new_name": ".."})
        self.assertFalse(ok)

    def test_plan_question_contains_catalog(self):
        q = ops.plan_question("整理下载文件夹")
        self.assertIn("mkdir", q)
        self.assertIn("delete", q)
        self.assertIn("回收站", q)


class TestOpsExecute(unittest.TestCase):
    """真实文件操作在临时目录里跑；删除 mock 成直接删（不污染回收站）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_mkdir_move_copy_rename_find(self):
        src = self.root / "a.txt"
        src.write_text("hello", encoding="utf-8")
        dst = self.root / "目标"
        self.assertIn("就绪", ops.execute({"op": "mkdir", "path": str(dst)}))
        ops.execute({"op": "move", "src": str(src), "dst_dir": str(dst)})
        self.assertFalse(src.exists())
        self.assertTrue((dst / "a.txt").exists())
        ops.execute({"op": "copy", "src": str(dst / "a.txt"), "dst_dir": str(self.root)})
        self.assertTrue((self.root / "a.txt").exists())
        ops.execute({"op": "rename", "path": str(self.root / "a.txt"), "new_name": "b.txt"})
        self.assertTrue((self.root / "b.txt").exists())
        found = ops.execute({"op": "find_files", "root": str(self.root), "pattern": "*.txt"})
        self.assertIn("b.txt", found)
        listing = ops.execute({"op": "list_dir", "path": str(self.root)})
        self.assertIn("目标", listing)
        stats = ops.execute({"op": "dir_stats", "path": str(self.root), "top": 3})
        self.assertIn("B", stats)          # 文件很小就是 B 级

    def test_delete_goes_through_recycle_helper(self):
        victim = self.root / "victim.txt"
        victim.write_text("x", encoding="utf-8")
        with mock.patch.object(ops, "recycle", side_effect=lambda p: os.remove(p)) as rec:
            result = ops.execute({"op": "delete", "path": str(victim)})
        rec.assert_called_once_with(str(victim))
        self.assertFalse(victim.exists())
        self.assertIn("回收站", result)

    def test_execute_missing_src_fails_clean(self):
        with self.assertRaises(FileNotFoundError):
            ops.execute({"op": "move", "src": str(self.root / "不存在.txt"),
                         "dst_dir": str(self.root)})

    def test_launch_app_uses_index(self):
        lnk = self.root / "记事本.lnk"
        lnk.write_bytes(b"")
        with mock.patch.object(ops.os, "startfile") as sf:
            result = ops.execute({"op": "launch_app", "name": "记事"},
                                 {"记事本": str(lnk)})
        sf.assert_called_once_with(str(lnk))
        self.assertIn("记事本", result)

    def test_start_menu_index_builds(self):
        appdata = os.environ.get("APPDATA")
        index = ops.start_menu_apps()
        if appdata and (pathlib.Path(appdata) / "Microsoft/Windows/Start Menu").exists():
            self.assertGreater(len(index), 0, "真实机器上开始菜单索引不该为空")


class TestScheduler(unittest.TestCase):
    def test_after_fires_with_payload(self):
        _app()
        got = []
        sch = scheduler.Scheduler()
        sch.fired.connect(lambda name, payload: got.append((name, payload)))
        sch.after("test", 0.2, {"msg": "喝水"})
        self.assertTrue(_wait(lambda: bool(got), timeout=5))
        self.assertEqual(got[0], ("test", {"msg": "喝水"}))

    def test_cancel_and_override(self):
        _app()
        got = []
        sch = scheduler.Scheduler()
        sch.fired.connect(lambda name, payload: got.append(name))
        sch.after("a", 5)
        sch.after("a", 0.1)          # 同名覆盖
        time.sleep(0.3)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(got, ["a"])  # 旧的 5 秒定时器被覆盖，只响新的


class TestDocExtract(unittest.TestCase):
    """PDF / DOCX / TXT 提取（临时造文件）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_txt(self):
        f = self.root / "笔记.md"
        f.write_text("# 数据结构\n链表是一种线性结构", encoding="utf-8")
        text = study.extract_doc_text(str(f))
        self.assertIn("链表", text)

    def test_pdf(self):
        import pymupdf
        f = self.root / "课件.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Linked List 2026: single linked list")
        doc.save(str(f))
        doc.close()
        text = study.extract_doc_text(str(f))
        self.assertIn("Linked List", text)

    def test_docx(self):
        import docx
        f = self.root / "讲义.docx"
        d = docx.Document()
        d.add_paragraph("循环队列的判满条件")
        d.save(str(f))
        text = study.extract_doc_text(str(f))
        self.assertIn("循环队列", text)

    def test_unsupported_raises(self):
        f = self.root / "x.exe"
        f.write_bytes(b"")
        with self.assertRaises(ValueError):
            study.extract_doc_text(str(f))


class TestGlossaryBuilder(unittest.TestCase):
    def test_build_glossary_question(self):
        q = study.build_glossary_question("讲单链表", ["问：什么是头插法"])
        self.assertIn("术语表", q)
        self.assertIn("单链表", q)
        self.assertIn("什么是头插法", q)


class TestStoreFrameTextAndReview(unittest.TestCase):
    def test_frame_text_roundtrip(self):
        conn = store.connect(":memory:")
        store.add_frame_text(conn, "D:/x/录屏/frame_1.jpg", "2026-10-07 10:00:00", "板书文字")
        store.add_frame_text(conn, "D:/x/录屏/frame_1.jpg", "2026-10-07 10:00:00", "覆盖更新")
        rows = store.frame_text_between(conn, "2026-10-07 00:00:00", "2026-10-08 00:00:00")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "覆盖更新")

    def test_due_starred_1_3_7(self):
        conn = store.connect(":memory:")
        today = datetime.date.today()
        for days_ago in (0, 1, 3, 7):
            ask_id = store.add_ask(conn, f"问题{days_ago}", "答案", 1, "m", starred=True)
            ts = (datetime.datetime.now() - datetime.timedelta(days=days_ago)
                  ).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE asks SET ts = ? WHERE id = ?", (ts, ask_id))
        conn.commit()
        due = store.due_starred(conn, today)
        self.assertEqual(len(due), 3, "今天问的不该提醒，1/3/7 天前的该提醒")
        store.bump_review_stage(conn, due)
        self.assertEqual(len(store.due_starred(conn, today)), 0, "提醒过推进度，不再重复")


class TestBarAssistant(unittest.TestCase):
    """> 前缀、文档挂载、多图穿透。"""

    def setUp(self):
        _app()
        self.b = bar.AskBar("Alt+Q")
        self.addCleanup(self.b.shutdown)
        self.addCleanup(self.b.deleteLater)

    def test_gt_prefix_emits_computer_request(self):
        got = []
        self.b.computer_request.connect(lambda t: got.append(t))
        self.b.ask.setText("> 把下载里的 pdf 整理到课件")
        self.b.submit()
        self.assertEqual(got, ["把下载里的 pdf 整理到课件"])
        self.assertEqual(self.b.ask.text(), "")

    def test_set_doc_and_send(self):
        captured = {}

        class FakeWorker:
            finished = mock.MagicMock()
            chunk = mock.MagicMock()
            done = mock.MagicMock()
            failed = mock.MagicMock()

            def __init__(self, image_path, question, history, parent=None, context="",
                         extra_images=None):
                captured.update(question=question, extra_images=extra_images)

            def start(self):
                pass

            def cancel(self):
                pass

            def wait(self, ms):
                return True

        self.b.set_doc("D:/课件/第三章.pdf", "第三章讲队列的链式存储……")
        self.assertIn("第三章.pdf", self.b.ask.placeholderText())
        self.b.ask.setText("这章讲了什么")
        with mock.patch.object(bar, "_AskWorker", FakeWorker):
            self.b.submit()
        self.assertIn("【参考文档：第三章.pdf】", captured["question"])
        self.assertIn("这章讲了什么", captured["question"])
        self.b._drop_running()

    def test_append_text_adds_to_answer(self):
        self.b.append_text("✓ 已完成第 1 步")
        self.assertIn("✓ 已完成第 1 步", self.b.answer.toPlainText())


class TestOcrQueue(unittest.TestCase):
    """OCR 队列：文字落 frame_text 表（引擎 mock，不真识别）。"""

    def setUp(self):
        _app()
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_enqueue_ocr_lands_in_db(self):
        from learnsys.ask import ocr
        q = ocr.OcrQueue(lambda: self.conn)
        got = []
        q.text_ready.connect(lambda p, t: got.append((p, t)))
        with mock.patch.object(ocr, "ocr_image", return_value="板书：哈夫曼树"):
            q.enqueue("D:/x/frame_1.jpg", "2026-10-07 10:00:00")
            self.assertTrue(_wait(lambda: bool(got), timeout=10))
        rows = store.frame_text_between(self.conn, "2026-10-07 00:00:00",
                                        "2026-10-08 00:00:00")
        self.assertEqual(len(rows), 1)
        self.assertIn("哈夫曼树", rows[0][2])

    def test_ocr_failure_does_not_kill_queue(self):
        from learnsys.ask import ocr
        q = ocr.OcrQueue(lambda: self.conn)
        calls = []

        def flaky(path):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("第一张崩")
            return "第二张的文字"

        with mock.patch.object(ocr, "ocr_image", side_effect=flaky):
            q.enqueue("D:/x/1.jpg", "2026-10-07 10:00:00")
            q.enqueue("D:/x/2.jpg", "2026-10-07 10:01:00")
            self.assertTrue(_wait(lambda: len(store.frame_text_between(
                self.conn, "2026-10-07 00:00:00", "2026-10-08 00:00:00")) == 1, timeout=10))



class TestAskAppBoots(unittest.TestCase):
    """整只 app 要能真正构造出来 —— 防止「单元全绿但接线炸了」（真踩过：import 行没打上）。"""

    def test_construct_askapp(self):
        from learnsys.ask import app as app_mod
        a = _app()
        app_obj = app_mod.AskApp(a)
        self.addCleanup(app_obj.bar.shutdown)
        self.addCleanup(app_obj.caller.close)
        self.assertFalse(app_obj.live.recording)
        self.assertIsNotNone(app_obj.scheduler)
        self.assertIsNotNone(app_obj._ocr)
        # 托盘菜单动作都在
        self.assertIsNotNone(app_obj.record_action)


if __name__ == "__main__":
    unittest.main(verbosity=2)
