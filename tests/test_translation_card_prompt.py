# -*- coding: utf-8 -*-
"""整篇翻译复习卡：正面必须是中文原文，学生英文放在背面。"""
from __future__ import annotations

import unittest

from learnsys.train.review import (_translation_cards,
                                   translation_sentence_card)

PACK = {
    "id": "t99",
    "segments": [
        {"zh": "春节是中国最重要的传统节日。",
         "reference": "The Spring Festival is the most important traditional festival in China."},
        {"zh": "人们会打扫房屋、贴春联。",
         "reference": "People clean their homes and put up spring couplets."},
    ],
}

TEXT = ("The Spring Festival is the most important festival in China. "
        "People clean their homes and put up couplets.")


def _error(quote: str, fix: str = "better wording") -> dict:
    return {"type": "用词", "severity": "严重", "quote": quote,
            "fix": fix, "why": "说明", "gloss": ""}


class TranslationCardPromptTest(unittest.TestCase):
    def test_question_is_chinese_and_my_answer_is_student_english(self):
        alignment = [
            {"segment": 1,
             "quote": "The Spring Festival is the most important festival in China."},
            {"segment": 2, "quote": "People clean their homes and put up couplets."},
        ]
        cards = _translation_cards(
            PACK, TEXT, [_error("most important"), _error("couplets")], alignment)
        self.assertEqual(len(cards), 2)
        first, second = cards
        self.assertEqual(first["question"], PACK["segments"][0]["zh"])
        self.assertEqual(second["question"], PACK["segments"][1]["zh"])
        self.assertEqual(first["my_answer"], alignment[0]["quote"])
        self.assertEqual(second["my_answer"], alignment[1]["quote"])
        self.assertEqual(first["source_id"], "translation:t99:seg1")
        self.assertEqual(second["source_id"], "translation:t99:seg2")
        self.assertNotIn("Spring Festival is", first["question"])

    def test_same_segment_errors_make_one_card(self):
        alignment = [{"segment": 1,
                      "quote": "The Spring Festival is the most important festival in China."}]
        cards = _translation_cards(
            PACK, TEXT, [_error("most important"), _error("Spring Festival")],
            alignment)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["source_id"], "translation:t99:seg1")
        self.assertIn("most important", cards[0]["answer"])
        self.assertIn("Spring Festival", cards[0]["answer"])

    def test_without_alignment_uses_reference_similarity(self):
        cards = _translation_cards(PACK, TEXT, [_error("couplets")], [])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["question"], PACK["segments"][1]["zh"])
        self.assertIn("People clean their homes", cards[0]["my_answer"])

    def test_legacy_signature_keeps_student_sentence_as_question(self):
        card = translation_sentence_card(
            "translation:t99", "A student sentence.", [_error("student")])
        self.assertEqual(card["question"], "A student sentence.")
        self.assertIn("translation:t99:", card["source_id"])


if __name__ == "__main__":
    unittest.main()
