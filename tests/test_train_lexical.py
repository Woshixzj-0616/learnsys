# -*- coding: utf-8 -*-
"""生词本准入与整句卡：碎片不进生词本，句子问题按整句建卡。"""
from __future__ import annotations

import unittest

from learnsys.train import lexical, review


class LexicalGateTest(unittest.TestCase):
    def test_spelling_accepts_single_word_only(self):
        entry = lexical.as_vocab_entry(
            error_type="拼写", quote="accommendation", fix="accommodation",
            gloss="住宿")
        self.assertEqual(entry, ("accommodation", "住宿"))
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="拼写", quote="in different site",
            fix="in different regions", gloss="地区"))

    def test_multiword_only_terms_or_proper_nouns(self):
        # 普通搭配/句子片段改错留在整句卡，不进生词本
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="is largely different",
            fix="vary greatly", gloss="差异很大"))
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="x", fix="financial support",
            gloss="经济支持"))
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="x", fix="pay New Year greetings to",
            gloss="拜年"))
        # 术语表里的术语、明显专有名词仍收
        self.assertEqual(
            lexical.as_vocab_entry(
                error_type="术语", quote="spring paper",
                fix="abundance year after year",
                terms=[{"zh": "年年有余", "en": "abundance year after year"}])[0],
            "abundance year after year")
        self.assertEqual(
            lexical.as_vocab_entry(error_type="术语", quote="x",
                                   fix="the Chinese Dream", gloss="中国梦")[0],
            "the Chinese Dream")
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="x", fix="one two three four five",
            gloss="一"))
        # 术语表里的多译法（带 /）也要能匹配
        self.assertEqual(
            lexical.as_vocab_entry(
                error_type="术语", quote="x",
                fix="remote medicine / telemedicine",
                terms=[{"zh": "远程医疗",
                        "en": "remote medicine / telemedicine"}])[0],
            "remote medicine / telemedicine")

    def test_sentence_types_never_enter_vocab(self):
        for kind in ("语法", "标点", "漏译", "误译", "改变原意", "结构", "中式英语"):
            with self.subTest(kind=kind):
                self.assertIsNone(lexical.as_vocab_entry(
                    error_type=kind, quote="School should",
                    fix="Schools should", why="主谓一致"))
        # 就算模型标成「用词」，主谓片段也不能进生词本
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="用词", quote="government invests",
            fix="the government has invested", gloss="政府已投入"))

    def test_gloss_becomes_meaning_prefix(self):
        entry = lexical.as_vocab_entry(
            error_type="术语", quote="eletronic payment", fix="electronic payment",
            why="拼写错误", gloss="电子支付",
            terms=[{"zh": "电子支付", "en": "electronic payment"}])
        self.assertEqual(entry, ("electronic payment", "电子支付｜拼写错误"))
        # 非中文 gloss 不算释义；没有术语表就不入本，why 不能冒充释义
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="术语", fix="electronic payment", why="拼写错误",
            gloss="electronic payment"))

    def test_term_table_supplies_meaning(self):
        # 模型没给 gloss 时，用题库术语表里的中文，而不是错因说明
        entry = lexical.as_vocab_entry(
            error_type="术语", quote="eletronic payment", fix="electronic payment",
            why="电子支付拼写错误",
            terms=[{"zh": "电子支付", "en": "electronic payment"}])
        self.assertEqual(entry, ("electronic payment", "电子支付"))
        entry = lexical.as_vocab_entry(
            error_type="术语", quote="the spring festival",
            fix="the Spring Festival", gloss="",
            terms=[{"zh": "春节", "en": "the Spring Festival"}])
        self.assertEqual(entry, ("the Spring Festival", "春节"))
        # 术语表也查不到：不入本，避免「……拼写错误」这种假释义
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="术语", quote="x", fix="breakthroughts",
            why="拼写错误", terms=[{"zh": "电子支付", "en": "electronic payment"}]))
        # 多词拼写：术语表认它才收（electronic payments → electronic payment）
        self.assertEqual(
            lexical.as_vocab_entry(
                error_type="拼写", quote="eletronic payment",
                fix="electronic payments", why="拼写错误",
                terms=[{"zh": "电子支付", "en": "electronic payment"}]),
            ("electronic payments", "电子支付"))
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="拼写", quote="x", fix="chinese culture",
            gloss="中国文化"))

    def test_sentence_punctuation_and_cjk_rejected(self):
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="a", fix="climate, diet and lifestyle"))
        self.assertIsNone(lexical.as_vocab_entry(
            error_type="搭配", quote="a", fix="vary 很大"))

    def test_historical_shape_is_conservative(self):
        # 旧数据没有可信的错误类型，形态判断要同时挡住词数超限与主谓片段。
        self.assertTrue(lexical.is_lexical_shape("vary greatly"))
        self.assertTrue(lexical.is_lexical_shape("have an insight"))
        self.assertTrue(lexical.is_lexical_shape("the dropout rate"))
        self.assertTrue(lexical.is_lexical_shape("financial support"))
        self.assertTrue(lexical.is_lexical_shape("the reunion dinner"))
        self.assertTrue(lexical.is_lexical_shape("travel to the countryside"))
        self.assertTrue(lexical.is_lexical_shape("abundance year after year"))
        self.assertFalse(lexical.is_lexical_shape("some cities have restricted"))
        self.assertFalse(lexical.is_lexical_shape("Schools should"))
        self.assertFalse(lexical.is_lexical_shape("The research demonstrates"))
        self.assertFalse(lexical.is_lexical_shape("The government has invested"))
        self.assertFalse(lexical.is_lexical_shape("has shrunk"))
        self.assertFalse(lexical.is_lexical_shape("and also reduces"))
        self.assertFalse(lexical.is_lexical_shape("only in recent years"))
        self.assertFalse(lexical.is_lexical_shape(
            "the rate of dropping out of school"))

    def test_proper_noun_shape(self):
        for word in ("the Chinese Dream",
                     "the Chang'e lunar exploration project",
                     "the Spring Festival"):
            with self.subTest(word=word):
                self.assertTrue(lexical.is_proper_noun_shape(word))
        # 不以限定词开头的大写短语交给题库术语表兜底（New Year's Eve 在 t01 术语表里）
        for word in ("New Year's Eve", "pay New Year greetings to",
                     "the government has invested",
                     "a powerful driving force",
                     "financial support",
                     "Schools should"):
            with self.subTest(word=word):
                self.assertFalse(lexical.is_proper_noun_shape(word))


class SentenceCardTest(unittest.TestCase):
    PACK = {"id": "t99", "source_zh": "第一句。第二句。",
            "info_points": [], "segments": [], "terms": []}

    def test_sentence_around_expands_to_full_sentence(self):
        text = "First one is bad. Second one is also bad!"
        self.assertEqual(review.sentence_around(text, "also bad"),
                         "Second one is also bad!")
        self.assertEqual(review.sentence_around(text, "zzz"), "zzz")

    def test_translation_groups_errors_by_full_sentence(self):
        text = ("First sentence has a error here. "
                "Second sentence is also wrong there. "
                "Third sentence has one minor thing.")
        pack = dict(self.PACK, source_zh="a" * 120)
        result = review.validate_translation({
            "band": 10, "band_reason": "测试",
            "errors": [
                {"type": "语法", "severity": "严重",
                 "quote": "a error", "fix": "an error", "why": "冠词"},
                {"type": "搭配", "severity": "一般",
                 "quote": "also wrong", "fix": "also incorrect", "why": "搭配",
                 "gloss": "也不正确"},
                {"type": "语法", "severity": "严重",
                 "quote": "wrong there", "fix": "incorrect there", "why": "用词"},
                {"type": "搭配", "severity": "一般",
                 "quote": "minor thing", "fix": "minor issue", "why": "搭配",
                 "gloss": "小问题"},
            ],
        }, text, pack)
        cards = {card["question"]: card for card in result["cards"]}
        self.assertEqual(len(cards), 2, "只有含严重错误的句子建卡")
        first = cards["First sentence has a error here."]
        self.assertIn("`a error` → **an error**", first["answer"])
        second = cards["Second sentence is also wrong there."]
        self.assertIn("`also wrong` → **also incorrect**", second["answer"])
        self.assertIn("`wrong there` → **incorrect there**", second["answer"])
        self.assertEqual(second["note"], "2 处必改 · 整句重译")
        # 普通搭配改错只留在整句卡，不再进生词本
        self.assertEqual(result["vocab_cards"], [])

    def test_sentence_card_uses_chinese_front_and_full_answer(self):
        item = {"id": "x999", "zh": "学校应为学生提供心理辅导。",
                "reference": "Schools should provide psychological counselling."}
        text = "School should provide psychological instruction."
        result = review.validate_sentence({
            "conclusion": "有偏差",
            "info_points": {"total": 1, "covered": 1, "missing": []},
            "must_fix": [
                {"type": "语法", "quote": "School should",
                 "fix": "Schools should", "why": "主谓一致"},
                {"type": "搭配", "quote": "psychological instruction",
                 "fix": "psychological counselling", "why": "搭配",
                 "gloss": "心理辅导"},
            ],
            "suggestions": [],
            "minimal_fix": "Schools should provide psychological counselling.",
        }, text, item)
        self.assertEqual(len(result["cards"]), 1)
        card = result["cards"][0]
        self.assertEqual(card["source_id"], "sentence:x999")
        self.assertEqual(card["question"], item["zh"])
        self.assertEqual(card["my_answer"], text)
        self.assertIn("`School should` → **Schools should**", card["answer"])
        self.assertIn("`psychological instruction` → **psychological counselling**",
                      card["answer"])
        # 普通搭配改错只留在整句卡，不再进生词本
        self.assertEqual(result["vocab_cards"], [])


if __name__ == "__main__":
    unittest.main()
