# -*- coding: utf-8 -*-
"""生词明显变体：alias 规则、add_vocab 合并、历史分组。"""
from __future__ import annotations

import unittest

from learnsys import store
from learnsys.store.wordkey import aliases_match, word_aliases


class WordAliasTest(unittest.TestCase):
    def test_plural_and_case(self):
        self.assertTrue(aliases_match("Caravans", "caravan"))
        self.assertTrue(aliases_match("charging piles", "charging pile"))
        self.assertTrue(aliases_match("passes", "pass"))

    def test_article_and_punctuation(self):
        self.assertTrue(aliases_match("the Silk Road", "Silk Road"))
        self.assertTrue(aliases_match("New Year's Eve", "New Years Eve"))

    def test_slash_alternatives(self):
        self.assertTrue(aliases_match(
            "remote medicine / telemedicine", "remote medicine"))
        self.assertTrue(aliases_match(
            "remote medicine / telemedicine", "telemedicine"))
        self.assertTrue(aliases_match("advocate / uphold", "uphold"))

    def test_parenthetical_abbreviation(self):
        self.assertTrue(aliases_match(
            "digital RMB (e-CNY)", "digital RMB"))
        self.assertTrue(aliases_match(
            "digital RMB (e-CNY)", "e-CNY"))
        self.assertTrue(aliases_match(
            "the Belt and Road Initiative (BRI)", "BRI"))

    def test_synonyms_are_not_forced_together(self):
        # 同义但拼写不同，交给迁移工具报告，不自动合并。
        self.assertFalse(aliases_match("high-speed rail", "high-speed railway"))
        self.assertEqual(word_aliases(""), set())


class VocabAliasStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_add_merges_plural_variant(self):
        first, created = store.add_vocab(
            self.conn, word="Caravans", meaning="商队")
        self.assertTrue(created)
        second, created_again = store.add_vocab(
            self.conn, word="caravan", meaning="商队")
        self.assertFalse(created_again)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM vocab_items").fetchone()[0], 1)

    def test_add_merges_slash_variant(self):
        first, _ = store.add_vocab(
            self.conn, word="remote medicine / telemedicine", meaning="远程医疗")
        second, created = store.add_vocab(
            self.conn, word="telemedicine", meaning="远程医疗")
        self.assertFalse(created)
        self.assertEqual(second["id"], first["id"])

    def test_add_merges_article_variant(self):
        first, _ = store.add_vocab(
            self.conn, word="the Silk Road", meaning="丝绸之路")
        second, created = store.add_vocab(
            self.conn, word="Silk Road", meaning="丝绸之路")
        self.assertFalse(created)
        self.assertEqual(second["id"], first["id"])

    def test_archived_variant_is_restored(self):
        first, _ = store.add_vocab(self.conn, word="Caravans", meaning="商队")
        store.update_vocab(self.conn, first["id"], status="archived")
        second, created = store.add_vocab(
            self.conn, word="caravan", meaning="商队")
        self.assertFalse(created)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["status"], "active")

    def test_find_active_word_matches_variant(self):
        item, _ = store.add_vocab(self.conn, word="Caravans", meaning="商队")
        found = store.find_active_word(self.conn, "caravan")
        self.assertEqual(found["id"], item["id"])

    def test_archived_bridge_merges_into_active(self):
        active, _ = store.add_vocab(
            self.conn, word="telemedicine", meaning="远程医疗")
        self.conn.execute(
            "INSERT INTO vocab_items (word, normalized, meaning, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, 'archived', 'test', '', '')",
            ("remote medicine / telemedicine",
             "remote medicine / telemedicine", "远程医疗"))
        self.conn.commit()
        merged, created = store.add_vocab(
            self.conn, word="remote medicine", meaning="远程医疗")
        self.assertFalse(created)
        self.assertEqual(merged["id"], active["id"])

    def test_active_aliases_include_archived_bridge(self):
        store.add_vocab(self.conn, word="telemedicine", meaning="远程医疗")
        self.conn.execute(
            "INSERT INTO vocab_items (word, normalized, meaning, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, 'archived', 'test', '', '')",
            ("remote medicine / telemedicine",
             "remote medicine / telemedicine", "远程医疗"))
        self.conn.commit()
        aliases = store.active_vocab_aliases(self.conn)
        self.assertIn("telemedicine", aliases)
        self.assertIn("remote medicine", aliases)

    def test_different_meaning_is_not_merged(self):
        glass, created = store.add_vocab(
            self.conn, word="glass", meaning="玻璃")
        self.assertTrue(created)
        glasses, created_again = store.add_vocab(
            self.conn, word="glasses", meaning="眼镜")
        self.assertTrue(created_again)
        self.assertNotEqual(glasses["id"], glass["id"])

    def test_variant_groups_connect_chain(self):
        items = [
            {"id": 1, "word": "uphold"},
            {"id": 2, "word": "advocate / uphold"},
            {"id": 3, "word": "remote medicine"},
            {"id": 4, "word": "remote medicine / telemedicine"},
            {"id": 5, "word": "telemedicine"},
        ]
        groups = store.variant_groups(items)
        sizes = sorted(len(group) for group in groups)
        self.assertEqual(sizes, [2, 3])


if __name__ == "__main__":
    unittest.main()
