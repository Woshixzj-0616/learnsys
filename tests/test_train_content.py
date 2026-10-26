# -*- coding: utf-8 -*-
"""训练内容包：数量、结构、id 唯一、句子派生。"""
from __future__ import annotations

import unittest

from learnsys.train import content, validate


class TrainContentTest(unittest.TestCase):
    def test_release_counts(self):
        counts = validate.counts()
        self.assertEqual(counts["writing"], 24)
        self.assertEqual(counts["translation"], 24)
        self.assertEqual(counts["extra_sentences"], 120)
        self.assertEqual(counts["derived_sentences"], 192)
        self.assertEqual(counts["sentences"], 312)

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
        source_ids = {item["id"] for item in content.translation_items()}
        self.assertEqual({row["source_id"] for row in rows}, source_ids)
        for row in rows:
            self.assertIn(row["source_id"], source_ids)
            self.assertTrue(row["reference"])
            self.assertTrue(row["info_points"])
            self.assertIn(row["skill"], content.SKILLS)

    def test_lead_sentence_items(self):
        leads = [item for item in content.writing_items()
                 if item.get("lead_sentence")]
        self.assertEqual(len(leads), 12)
        for item in leads:
            self.assertEqual(item["type"], "首句续写")
            self.assertIn(item["lead_sentence"], item["prompt_en"])
            self.assertEqual(item["prompt_en"].count(item["lead_sentence"]), 1)
            self.assertTrue(
                item["model_essay"]["text"].startswith(item["lead_sentence"]))
            self.assertTrue(any(word in item["prompt_zh"]
                                for word in ("首句", "开头")))

    def test_old_items_have_no_lead(self):
        for item in content.writing_items():
            if item["id"] < "w13":
                self.assertNotIn("lead_sentence", item)

    def test_skills_evenly_distributed(self):
        counts = {}
        for item in content.extra_sentences():
            counts[item["skill"]] = counts.get(item["skill"], 0) + 1
        self.assertEqual(set(counts), set(content.SKILLS))
        for skill in content.SKILLS:
            self.assertGreaterEqual(counts[skill], 12, skill)

    def test_titles_and_texts_unique(self):
        fields = (
            ("writing", "title"), ("writing", "prompt_en"),
            ("writing", "lead_sentence"), ("translation", "source_zh"),
        )
        lib = content.library()
        for kind, key in fields:
            values = [item.get(key) for item in lib[kind] if item.get(key)]
            self.assertEqual(len(values), len(set(values)), f"{kind}.{key} 重复")
        zh = [item["zh"] for item in content.extra_sentences()]
        self.assertEqual(len(zh), len(set(zh)), "专项句中文重复")

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
