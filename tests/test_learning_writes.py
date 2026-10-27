# -*- coding: utf-8 -*-
"""P25.2 学习写入工具：生词加删、复习评档、训练错题。"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import tools


def _tomorrow() -> str:
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


class LearningWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        self.ctx = tools.ToolContext(data_root=self.root, db_path=self.db_path)
        self.conn = store.connect(self.db_path)
        self.addCleanup(self.conn.close)

    # ---------- add_vocab ----------

    def test_add_vocab_creates_card_due_tomorrow(self):
        text = tools.add_vocab("ubiquitous", "无处不在的", ctx=self.ctx)
        self.assertIn("已加进生词本", text)
        self.assertIn("ubiquitous", text)
        row = self.conn.execute(
            "SELECT id, meaning FROM vocab_items WHERE word = 'ubiquitous'").fetchone()
        self.assertIsNotNone(row)
        card = store.get_review_state(self.conn, "vocab", int(row[0]))
        self.assertEqual(card["due"], _tomorrow())

    def test_add_vocab_merges_without_overwriting(self):
        tools.add_vocab("ubiquitous", "", ctx=self.ctx)
        tools.add_vocab("ubiquitous", "无处不在的", ctx=self.ctx)
        rows = self.conn.execute(
            "SELECT meaning FROM vocab_items WHERE word = 'ubiquitous'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "无处不在的")
        # 已有释义不会被空值覆盖
        tools.add_vocab("ubiquitous", "", ctx=self.ctx)
        row = self.conn.execute(
            "SELECT meaning FROM vocab_items WHERE word = 'ubiquitous'").fetchone()
        self.assertEqual(row[0], "无处不在的")

    def test_add_vocab_rejects_empty_word(self):
        self.assertIn("空的", tools.add_vocab("   ", "x", ctx=self.ctx))
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM vocab_items").fetchone()[0], 0)

    # ---------- delete_vocab ----------

    def test_delete_vocab_by_word_removes_card(self):
        tools.add_vocab("apple", "苹果", ctx=self.ctx)
        item = self.conn.execute(
            "SELECT id FROM vocab_items WHERE word = 'apple'").fetchone()
        text = tools.delete_vocab(word="Apple", ctx=self.ctx)
        self.assertIn("已从生词本删除", text)
        self.assertIn("apple", text)
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM vocab_items WHERE word = 'apple'").fetchone())
        self.assertIsNone(
            store.get_review_state(self.conn, "vocab", int(item[0])))

    def test_delete_vocab_by_id(self):
        tools.add_vocab("pear", "梨", ctx=self.ctx)
        item_id = self.conn.execute("SELECT id FROM vocab_items").fetchone()[0]
        text = tools.delete_vocab(item_id=item_id, ctx=self.ctx)
        self.assertIn("已从生词本删除", text)
        self.assertIsNone(self.conn.execute("SELECT id FROM vocab_items").fetchone())

    def test_delete_vocab_not_found_lists_candidates(self):
        tools.add_vocab("apple", "苹果", ctx=self.ctx)
        text = tools.delete_vocab(word="appl", ctx=self.ctx)
        self.assertIn("没有「appl」", text)
        self.assertIn("apple", text)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM vocab_items").fetchone()[0], 1)

    def test_delete_vocab_needs_a_target(self):
        self.assertIn("哪个词", tools.delete_vocab(ctx=self.ctx))

    # ---------- rate_review ----------

    def test_rate_review_wrong_item_schedules_next(self):
        item_id, _ = store.add_wrong_item(
            self.conn, question="1 + 1 = ?", answer="2", my_answer="3",
            source="manual", source_id="manual:r1")
        text = tools.rate_review("wrong", item_id, 3, ctx=self.ctx)
        self.assertIn("记得", text)
        self.assertIn("下次复习", text)
        card = store.get_review_state(self.conn, "wrong", item_id)
        self.assertGreater(card["due"], datetime.date.today().isoformat())
        log = self.conn.execute(
            "SELECT count(*) FROM review_log WHERE item_type='wrong' AND item_id=?",
            (item_id,)).fetchone()[0]
        self.assertEqual(log, 1)

    def test_rate_review_vocab_item(self):
        tools.add_vocab("apple", "苹果", ctx=self.ctx)
        item_id = self.conn.execute("SELECT id FROM vocab_items").fetchone()[0]
        text = tools.rate_review("vocab", item_id, 1, ctx=self.ctx)
        self.assertIn("忘了", text)

    def test_rate_review_rejects_bad_rating_and_type(self):
        self.assertIn("1–4", tools.rate_review("wrong", 1, 5, ctx=self.ctx))
        self.assertIn("只能", tools.rate_review("ask", 1, 3, ctx=self.ctx))

    def test_rate_review_missing_card(self):
        text = tools.rate_review("wrong", 9999, 3, ctx=self.ctx)
        self.assertIn("没有找到", text)
        self.assertIn("9999", text)

    # ---------- save_training_error ----------

    def test_save_training_error_creates_and_dedupes(self):
        first = tools.save_training_error(
            "I go to school yesterday.", "I go to school yesterday.",
            "I went to school yesterday.", skill="时态", source="writing",
            ctx=self.ctx)
        self.assertIn("已收进训练错题", first)
        self.assertIn("写作", first)
        second = tools.save_training_error(
            "I go to school yesterday.", "I go to school yesterday.",
            "I went to school yesterday.", skill="时态", source="writing",
            ctx=self.ctx)
        self.assertIn("已经在错题本里", second)
        rows = self.conn.execute(
            "SELECT id, source, tags, answer FROM wrong_items").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "writing")
        self.assertEqual(rows[0][2], "时态")
        self.assertEqual(rows[0][3], "I went to school yesterday.")

    def test_save_training_error_translation_source(self):
        text = tools.save_training_error(
            "科技赋能中国医疗", "Technology gives power to Chinese medical.",
            "Technology empowers China's healthcare.", source="translation",
            ctx=self.ctx)
        self.assertIn("翻译", text)
        self.assertEqual(
            self.conn.execute("SELECT source FROM wrong_items").fetchone()[0],
            "translation")

    def test_save_training_error_requires_fields(self):
        self.assertIn("原句", tools.save_training_error("", "x", ctx=self.ctx))
        self.assertIn("你的写法", tools.save_training_error(
            "原句", "  ", ctx=self.ctx))

    def test_new_training_error_enters_review_queue(self):
        tools.save_training_error(
            "He go home.", "He go home.", "He goes home.", ctx=self.ctx)
        item_id = self.conn.execute("SELECT id FROM wrong_items").fetchone()[0]
        # 新收错题由复习队列懒补卡，明天出现
        queue = tools.due_reviews(ctx=self.ctx)
        self.assertIn("今天没有到期的复习", queue)
        store.seed_review_states(self.conn)
        card = store.get_review_state(self.conn, "wrong", item_id)
        self.assertIsNotNone(card)

    # ---------- schema / 入口裁剪 / 确认文案 ----------

    def test_schemas_registered_and_guarded(self):
        names = {schema["name"]
                 for schema in tools.schemas_for("explain", surface="ask")}
        for name in ("add_vocab", "delete_vocab", "rate_review",
                     "save_training_error"):
            self.assertIn(name, names)
            self.assertIn(name, tools.WRITE_TOOLS)
            self.assertIn(name, tools.CONFIRM_TOOLS)

    def test_surface_cuts(self):
        ask = {s["name"] for s in tools.schemas_for("explain", surface="ask")}
        quickbar = {s["name"] for s in tools.schemas_for("explain", surface="quickbar")}
        cet6 = {s["name"] for s in tools.schemas_for("explain", surface="cet6")}
        video = {s["name"] for s in tools.schemas_for("explain", surface="video")}
        quiz = {s["name"] for s in tools.schemas_for("quiz", surface="ask")}
        quick = {s["name"] for s in tools.schemas_for("quick", surface="ask")}

        self.assertTrue({"add_vocab", "delete_vocab", "rate_review",
                         "save_training_error"} <= ask)
        self.assertIn("add_vocab", quickbar)
        self.assertNotIn("delete_vocab", quickbar)
        self.assertNotIn("save_training_error", quickbar)
        self.assertTrue({"add_vocab", "save_training_error", "rate_review"} <= cet6)
        self.assertNotIn("delete_vocab", cet6)
        self.assertIn("add_vocab", video)
        self.assertNotIn("rate_review", video)
        self.assertFalse({"add_vocab", "delete_vocab", "rate_review",
                          "save_training_error"} & quiz)
        self.assertEqual(quick, {"save_memory", "forget_memory"})

    def test_write_summary_shows_target(self):
        add = tools.write_summary(
            "add_vocab", {"word": "ubiquitous", "meaning": "无处不在的"})
        self.assertIn("ubiquitous", add)
        self.assertIn("无处不在的", add)
        delete = tools.write_summary(
            "delete_vocab", {"word": "apple", "item_id": 12})
        self.assertIn("apple", delete)
        self.assertIn("12", delete)
        review = tools.write_summary(
            "rate_review", {"item_type": "wrong", "item_id": 7, "rating": 3,
                            "item_label": "1 + 1 = ?"})
        self.assertIn("错题 #7", review)
        self.assertIn("记得", review)
        self.assertIn("1 + 1", review)
        train = tools.write_summary(
            "save_training_error", {"question": "He go home."})
        self.assertIn("He go home", train)

    def test_selfcheck_accepts_newly_saved_training_error(self):
        from learnsys.agent import selfcheck
        evidence = selfcheck.Evidence()
        evidence.add("save_training_error", {},
                     "已收进训练错题（#2，写作）。明天会出现在复习队列。")
        self.assertEqual(
            selfcheck.verify("已收进训练错题 #2。", evidence), [])

    def test_execute_routes_new_tools(self):
        wrong_id, _ = store.add_wrong_item(
            self.conn, question="1 + 1 = ?", answer="2", my_answer="3",
            source="manual", source_id="manual:exec1")
        cases = [
            ("add_vocab", {"word": "apple", "meaning": "苹果"}, "加进了生词本"),
            ("rate_review",
             {"item_type": "wrong", "item_id": wrong_id, "rating": 3},
             "提交了复习评档"),
            ("save_training_error",
             {"question": "He go home.", "my_answer": "He go home."},
             "收进了训练错题"),
        ]
        for name, args, preview in cases:
            _text, got_preview, ok = tools.execute(name, args, self.ctx)
            self.assertEqual(got_preview, preview, name)
            self.assertTrue(ok, name)


if __name__ == "__main__":
    unittest.main()
