# -*- coding: utf-8 -*-
"""训练内容包：数量、结构、id 唯一、句子派生。"""
from __future__ import annotations

import unittest

from learnsys.train import content, validate


class TrainContentTest(unittest.TestCase):
    def test_release_counts(self):
        counts = validate.counts()
        self.assertEqual(counts["writing"], 12)
        self.assertEqual(counts["translation"], 12)
        self.assertGreaterEqual(counts["extra_sentences"], 60)
        self.assertGreaterEqual(counts["derived_sentences"], 70)
        self.assertGreaterEqual(counts["sentences"], 130)

    def test_structure_has_no_errors(self):
        errors = validate.check_library()
        self.assertEqual(errors, [], "\n".join(errors))

    def test_ids_are_unique(self):
        seen = set()
        for item in content.all_packs():
            self.assertNotIn(item["id"], seen)
            seen.add(item["id"])
        for item in content.sentence_items():
            self.assertNotIn(item["id"], seen)
            seen.add(item["id"])

    def test_derived_sentences_reference_source(self):
        rows = content.derived_sentences()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row["source_id"], {"t01", "t02", "t03", "t04",
                                             "t05", "t06", "t07", "t08",
                                             "t09", "t10", "t11", "t12"})
            self.assertTrue(row["reference"])
            self.assertTrue(row["info_points"])
            self.assertIn(row["skill"], content.SKILLS)

    def test_lookup_and_version(self):
        pack = content.pack("writing", "w01")
        self.assertIsNotNone(pack)
        self.assertEqual(pack["kind"], "writing")
        self.assertRegex(pack["content_version"], r"^[0-9a-f]{12}$")
        self.assertIsNone(content.pack("writing", "nope"))
        sentence = content.sentence("t01-s1")
        self.assertIsNotNone(sentence)
        self.assertEqual(sentence["origin"], "passage")
        self.assertIsNotNone(content.sentence("x001"))

    def test_every_translation_segment_is_practisable(self):
        for item in content.translation_items():
            for seg in item["segments"]:
                self.assertTrue(seg["zh"])
                self.assertTrue(seg["reference"])
                self.assertTrue(seg["keywords"])
                self.assertTrue(seg["skeleton"])
                self.assertTrue(seg["info_points"])
                self.assertIn(seg["skill"], content.SKILLS)


if __name__ == "__main__":
    unittest.main()
