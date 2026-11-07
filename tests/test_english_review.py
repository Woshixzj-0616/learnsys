# -*- coding: utf-8 -*-
"""英语复习：句子/词两个 tab 的来源过滤、每日新卡限流、今日计数。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class EnglishReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        self.translation_id, _ = store.add_wrong_item(
            conn, question="随着城市人口增加，住房面临压力。",
            answer="As the urban population grows, housing faces pressure.",
            source="translation")
        self.manual_id, _ = store.add_wrong_item(
            conn, question="什么是子网掩码？", answer="划分网络位和主机位",
            source="manual")
        for index in range(15):
            store.add_vocab(conn, word=f"word{index}", meaning=f"词义{index}",
                            source="cet6")
        # 新卡默认次日到期；先建状态，再把两类卡都拉到今天，模拟「到期队列」。
        store.seed_review_states(conn)
        today = dt.date.today().isoformat()
        conn.execute("UPDATE review_state SET due = ?", (today,))
        conn.commit()
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_sentence_tab_only_keeps_english_sources(self):
        body = self.client.get(
            "/api/review/queue?kind=sentence&limit=10", headers=AUTH).json()
        ids = [item["item_id"] for item in body["items"]]
        self.assertIn(self.translation_id, ids)
        self.assertNotIn(self.manual_id, ids)
        self.assertTrue(all(item["item_type"] == "wrong" for item in body["items"]))
        self.assertEqual(body["kind"], "sentence")

    def test_word_tab_only_keeps_vocab(self):
        body = self.client.get(
            "/api/review/queue?kind=word&limit=20", headers=AUTH).json()
        self.assertTrue(all(item["item_type"] == "vocab" for item in body["items"]))
        self.assertEqual(len(body["items"]), 10)
        self.assertEqual(body["new_remaining"], 10)

    def test_new_card_limit_counts_reviewed_today(self):
        first = self.client.get(
            "/api/review/queue?kind=word&limit=10", headers=AUTH).json()
        self.assertEqual(len(first["items"]), 10)
        card = first["items"][0]
        self.client.post(
            f"/api/review/vocab/{card['item_id']}", json={"rating": 3},
            headers=AUTH)
        second = self.client.get(
            "/api/review/queue?kind=word&limit=10", headers=AUTH).json()
        self.assertEqual(second["new_remaining"], 9)
        self.assertEqual(len(second["items"]), 9)

    def test_due_counts_split_by_kind(self):
        stats_sentence = self.client.get(
            "/api/review/stats?kind=sentence", headers=AUTH).json()
        stats_word = self.client.get(
            "/api/review/stats?kind=word", headers=AUTH).json()
        self.assertEqual(stats_sentence["due"], 1)
        self.assertEqual(stats_sentence["total"], 1)
        self.assertEqual(stats_word["due"], 15)
        self.assertEqual(stats_word["new"], 15)

    def test_today_payload_has_split_due(self):
        body = self.client.get("/api/today", headers=AUTH).json()
        self.assertEqual(body["due_sentence"], 1)
        self.assertEqual(body["due_word"], 15)


if __name__ == "__main__":
    unittest.main()
