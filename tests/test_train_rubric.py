# -*- coding: utf-8 -*-
"""评分口径：quote 校验、硬规则钳制、错误卡、三次取中位。"""
from __future__ import annotations

import unittest

from learnsys.train import content, review, rubric


class QuoteTest(unittest.TestCase):
    def test_exact_and_case_insensitive(self):
        text = "The Spring Festival is the most important festival in China."
        self.assertTrue(review.quote_in_text("Spring Festival", text))
        self.assertTrue(review.quote_in_text("spring festival", text))
        self.assertTrue(review.quote_in_text("most important festival", text))

    def test_punctuation_difference_is_tolerated(self):
        text = "The second paragraph, is vague and lacks an example."
        self.assertTrue(review.quote_in_text("The second paragraph is vague", text))

    def test_fabricated_quote_is_rejected(self):
        text = "Students can learn many things from part-time jobs."
        self.assertFalse(review.quote_in_text("students should study harder", text))
        self.assertFalse(review.quote_in_text("ab", text))

    def test_filter_drops_fake_and_dedupes(self):
        text = "I can learn many things from this job."
        raw = [
            {"type": "搭配", "severity": "严重", "quote": "learn many things",
             "fix": "gain practical experience", "why": "搭配不自然"},
            {"type": "搭配", "severity": "严重", "quote": "learn many things",
             "fix": "gain practical experience", "why": "重复"},
            {"type": "语法", "severity": "严重", "quote": "this job is very good",
             "fix": "this job is useful", "why": "编造"},
        ]
        rows, dropped = review.filter_errors(raw, text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(dropped, 1)
        self.assertEqual(rows[0]["fix"], "gain practical experience")


class BandTest(unittest.TestCase):
    def test_normalize_and_label(self):
        self.assertEqual(rubric.normalize_band("11"), 11)
        self.assertEqual(rubric.normalize_band(11.4), 11)
        self.assertIsNone(rubric.normalize_band(16))
        self.assertIsNone(rubric.normalize_band("x"))
        self.assertEqual(rubric.band_label(14), "13–15 分")
        self.assertEqual(rubric.band_label(0), "0 分")

    def test_median(self):
        self.assertEqual(rubric.band_median([13, 11, 12]), 12)
        self.assertEqual(rubric.band_median([13, 11]), 13)
        self.assertIsNone(rubric.band_median([]))

    def test_missing_cap_thresholds(self):
        self.assertEqual(rubric.missing_cap(4, 10)[0], 5)
        self.assertEqual(rubric.missing_cap(2, 10)[0], 8)
        self.assertIsNone(rubric.missing_cap(1, 10)[0])
        self.assertIsNone(rubric.missing_cap(0, 0)[0])


class HardRulesTest(unittest.TestCase):
    def test_writing_word_and_paragraph_flags(self):
        hard = rubric.inspect("writing", "Short text.", None,
                              {"pasted_chars": 30, "left_seconds": 45})
        codes = {row["code"] for row in hard["flags"]}
        self.assertIn("word_count", codes)
        self.assertIn("paragraphs", codes)
        self.assertIn("paste", codes)
        self.assertIn("left", codes)
        self.assertEqual(hard["word_count"], 2)

    def test_lead_sentence_flag(self):
        pack = content.pack("writing", "w13")
        lead = pack["lead_sentence"]
        ok = rubric.inspect("writing", f"{lead}\n\nMore text follows.", pack)
        self.assertNotIn("lead_sentence", {row["code"] for row in ok["flags"]})
        bad = rubric.inspect("writing", "I forgot the lead sentence.",
                             pack)
        self.assertIn("lead_sentence", {row["code"] for row in bad["flags"]})

    def test_template_ratio(self):
        text = ("With the development of society, every coin has two sides. "
                "In my opinion, we should work hard.")
        result = rubric.template_check(text)
        self.assertGreater(result["ratio"], 0.3)
        self.assertIn("with the development of", result["phrases"])

    def test_translation_length_flag(self):
        pack = content.pack("translation", "t01")
        hard = rubric.inspect("translation", "Too short.", pack)
        self.assertTrue(any(row["code"] == "length" for row in hard["flags"]))


class ValidateTest(unittest.TestCase):
    def test_writing_off_topic_caps_band_and_filters_quotes(self):
        pack = content.pack("writing", "w01")
        text = ("I think part-time jobs are good because students can learn "
                "many things from them. In my opinion, it is a good choice.")
        obj = {
            "band": 12, "band_reason": "结构清楚", "off_topic": True,
            "dimensions": {"content": 3, "structure": 3, "language": 2,
                           "idiomatic": 1},
            "errors": [
                {"type": "搭配", "severity": "严重",
                 "quote": "learn many things", "fix": "gain practical experience",
                 "why": "搭配不自然"},
                {"type": "语法", "severity": "严重",
                 "quote": "students should study harder", "fix": "students should study",
                 "why": "编造"},
            ],
            "priorities": ["a", "b", "c"],
            "rewrite_task": "只改语搭配",
        }
        result = review.validate_writing(obj, text, pack)
        self.assertEqual(result["band"], 5)
        self.assertIn("跑题", result["band_reason"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors_dropped"], 1)
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["source"], "writing")

    def test_structural_errors_stay_out_of_wrongbook(self):
        pack = content.pack("writing", "w01")
        text = "Part-time jobs are good, but the essay has no paragraphs."
        obj = {
            "band": 9,
            "errors": [
                {"type": "结构", "severity": "严重",
                 "quote": "the essay has no paragraphs", "fix": "分三段",
                 "why": "结构问题不能独立重练"},
            ],
        }
        result = review.validate_writing(obj, text, pack)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["cards"], [])

    def test_translation_missing_points_cap_and_term_card(self):
        pack = content.pack("translation", "t01")
        text = pack["reference"]
        obj = {
            "band": 14, "band_reason": "整体准确",
            "info_points": {"missing": ["ip1", "ip2", "ip3", "ip4", "ip99"]},
            "alignment": [
                {"segment": 2, "quote": "Spring Festival"},
                {"segment": 99, "quote": "Spring Festival"},
                {"segment": 3, "quote": "not in the translation"},
            ],
            "errors": [
                {"type": "术语", "severity": "严重",
                 "quote": "Spring Festival", "fix": "the Spring Festival",
                 "why": "专有名词需要冠词"},
            ],
            "dimensions": {"coverage": 3, "accuracy": 4, "fluency": 4,
                           "terminology": 3},
        }
        result = review.validate_translation(obj, text, pack)
        self.assertEqual(result["band"], 5)
        self.assertEqual(result["info_points"]["total"], 10)
        self.assertEqual(result["info_points"]["covered"], 6)
        self.assertEqual(result["alignment"], [{"segment": 2, "quote": "Spring Festival"}])
        self.assertEqual(len(result["term_cards"]), 1)
        self.assertEqual(len(result["cards"]), 1)

    def test_translation_unknown_missing_does_not_cap(self):
        pack = content.pack("translation", "t01")
        result = review.validate_translation(
            {"band": 12, "info_points": "oops"}, pack["reference"], pack)
        self.assertEqual(result["band"], 12)
        self.assertFalse(result["info_points"]["known"])

    def test_sentence_keeps_pack_reference_and_filters(self):
        item = content.sentence("t01-s1")
        text = "Spring Festival is the most important traditional festival in China."
        obj = {
            "conclusion": "基本准确",
            "info_points": {"total": 1, "covered": 1, "missing": []},
            "must_fix": [
                {"quote": "most important", "fix": "the most important",
                 "why": "缺冠词"},
                {"quote": "very important", "fix": "important", "why": "编造"},
            ],
            "suggestions": [
                {"quote": "traditional festival", "fix": "traditional art",
                 "why": "更简洁"},
            ],
            "variants": ["The Spring Festival is China's most important traditional festival."],
            "minimal_fix": "The Spring Festival is the most important traditional festival in China.",
            "idiomatic": "The Spring Festival is China's foremost traditional festival.",
        }
        result = review.validate_sentence(obj, text, item)
        self.assertEqual(result["reference"], item["reference"])
        self.assertEqual(len(result["must_fix"]), 1)
        self.assertEqual(result["errors_dropped"], 1)
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(len(result["variants"]), 1)

    def test_merge_reviews_median_and_instability(self):
        samples = [
            {"band": 11, "band_reason": "a"},
            {"band": 13, "band_reason": "b"},
            {"band": 12, "band_reason": "c"},
        ]
        result = review.merge_reviews(samples, "writing")
        self.assertEqual(result["band"], 12)
        self.assertEqual(result["stability"]["spread"], 2)
        self.assertFalse(result["stability"]["stable"])
        self.assertIn("不稳定", result["band_reason"])

    def test_merge_requires_a_valid_band(self):
        with self.assertRaises(ValueError):
            review.merge_reviews([{"band": None}], "writing")


if __name__ == "__main__":
    unittest.main()
