# -*- coding: utf-8 -*-
"""P14 统一复习队列：到期卡、四档提交、日志、统计、兼容包装。"""
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


class ReviewApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        self.item_id, _ = store.add_wrong_item(
            conn, question="什么是子网掩码？", answer="用来划分网络位和主机位",
            source="manual")
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        conn.execute("UPDATE wrong_items SET ts = ? WHERE id = ?",
                     (f"{yesterday} 09:00:00", self.item_id))
        conn.commit()
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_token_required(self):
        self.assertEqual(self.client.get("/api/review/queue").status_code, 403)

    def test_queue_lists_due_wrong_item(self):
        body = self.client.get("/api/review/queue", headers=AUTH).json()
        self.assertEqual(body["count"], 1)
        item = body["items"][0]
        self.assertEqual(item["item_type"], "wrong")
        self.assertEqual(item["item_id"], self.item_id)
        self.assertIn("子网掩码", item["question"])
        self.assertEqual(item["state"], "new")

    def test_review_writes_state_and_log(self):
        response = self.client.post(
            f"/api/review/wrong/{self.item_id}", json={"rating": 3}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"]["reps"], 1)
        self.assertEqual(body["state"]["scheduled_days"], 3)
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute(
            "SELECT count(*) FROM review_log").fetchone()[0], 1)
        self.assertEqual(conn.execute(
            "SELECT rating FROM review_log").fetchone()[0], 3)
        self.assertEqual(conn.execute(
            "SELECT state FROM review_state").fetchone()[0], "review")

    def test_reviewed_card_leaves_queue_and_stats(self):
        self.client.post(
            f"/api/review/wrong/{self.item_id}", json={"rating": 3}, headers=AUTH)
        self.assertEqual(
            self.client.get("/api/review/queue", headers=AUTH).json()["count"], 0)
        stats = self.client.get("/api/review/stats", headers=AUTH).json()
        self.assertEqual(stats["due"], 0)
        self.assertEqual(stats["reviewed_today"], 1)
        self.assertEqual(stats["total"], 1)

    def test_compat_remember_maps_to_rating_3(self):
        response = self.client.post(
            f"/api/wrongbook/{self.item_id}/review",
            json={"result": "remember"}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["item"]["next_review"])
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute(
            "SELECT rating FROM review_log").fetchone()[0], 3)

    def test_compat_forgot_maps_to_rating_1(self):
        self.client.post(
            f"/api/wrongbook/{self.item_id}/review",
            json={"result": "remember"}, headers=AUTH)
        self.client.post(
            f"/api/wrongbook/{self.item_id}/review",
            json={"result": "forgot"}, headers=AUTH)
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute(
            "SELECT rating FROM review_log ORDER BY id DESC LIMIT 1").fetchone()[0], 1)
        self.assertEqual(conn.execute(
            "SELECT lapses FROM review_state").fetchone()[0], 1)

    def test_invalid_rating_and_type(self):
        self.assertEqual(self.client.post(
            f"/api/review/wrong/{self.item_id}", json={"rating": 9},
            headers=AUTH).status_code, 400)
        self.assertEqual(self.client.post(
            f"/api/review/ask/{self.item_id}", json={"rating": 3},
            headers=AUTH).status_code, 400)
        self.assertEqual(self.client.post(
            "/api/review/wrong/99999", json={"rating": 3},
            headers=AUTH).status_code, 404)

    def test_vocab_card_joins_same_queue(self):
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        vocab, _ = store.add_vocab(conn, word="subnet", meaning="子网")
        today = dt.date.today().isoformat()
        store.save_review_state(
            conn, "vocab", vocab["id"], state="new", due=today,
            stability=1.0, difficulty=5.0, reps=0, lapses=0,
            last_review="", scheduled_days=0, elapsed_days=0)
        body = self.client.get(
            "/api/review/queue?item_type=vocab", headers=AUTH).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["word"], "subnet")

    def test_vocab_stats_filter(self):
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        store.add_vocab(conn, word="subnet", meaning="子网")
        body = self.client.get(
            "/api/review/stats?item_type=vocab", headers=AUTH).json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["new"], 1)
        self.assertEqual(body["due"], 0, "新词明天才到期")
        wrong = self.client.get(
            "/api/review/stats?item_type=wrong", headers=AUTH).json()
        self.assertEqual(wrong["total"], 1, "错题卡不受生词影响")

    def test_seed_is_idempotent(self):
        self.client.get("/api/review/queue", headers=AUTH)
        self.client.get("/api/review/queue", headers=AUTH)
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute(
            "SELECT count(*) FROM review_state").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
