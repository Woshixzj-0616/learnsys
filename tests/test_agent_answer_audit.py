# -*- coding: utf-8 -*-
"""答案改口检测：只认结构性信号，避免把正常讲解判成改口。"""
from __future__ import annotations

import unittest

from learnsys.agent import answer_audit


class AnswerAuditTest(unittest.TestCase):
    def test_explicit_correction_hits(self):
        text = "答案选 C。我上面写错了，正确答案是 B。"
        self.assertEqual(answer_audit.check(text), "self_corrected")

    def test_option_changed_after_pause_hits(self):
        text = ("选 C，RL 型调整。\n"
                "等一下，我上面的说法和选项要对上：答案是 D。")
        self.assertEqual(answer_audit.check(text), "answer_changed")

    def test_normal_pause_does_not_hit(self):
        self.assertEqual(answer_audit.check("等一下，先看第一步。"), "")

    def test_clarification_does_not_hit(self):
        self.assertEqual(answer_audit.check("不是 C，而是 D。"), "")

    def test_option_listing_does_not_hit(self):
        text = ("A 顺序查找插入方便；B 折半查找要求有序；"
                "C 分块查找介于两者之间。答案选 D。")
        self.assertEqual(answer_audit.check(text), "")

    def test_code_and_quote_are_ignored(self):
        text = ("题干里写着：\n> 答案是 C。\n\n"
                "```text\n答案选 C……等一下……答案是 D\n```\n")
        self.assertEqual(answer_audit.check(text), "")

    def test_single_answer_is_fine(self):
        self.assertEqual(answer_audit.check("答案是 B。"), "")


if __name__ == "__main__":
    unittest.main()
