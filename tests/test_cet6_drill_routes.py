# -*- coding: utf-8 -*-
"""六级专项听写接口：令牌、队列、提交、统计。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app
from learnsys.services import cet6_drill

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class Cet6DrillRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="卷一",
            section="Section C 讲座/讲话", item="Recording 1",
            rows=[{"sentence": 1, "en": "For 60 years, cells divide forever.",
                   "note": "60听成6了", "plays": 10}], done=[1])
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="卷一",
            section="Section A 长对话", item="Conversation 1",
            rows=[{"sentence": 1, "en": "Hello there.", "note": "",
                   "plays": 0}], done=[])
        conn.close()

        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.cet6_patch = mock.patch.object(
            cet6_drill.config, "cet6_dir",
            return_value=pathlib.Path(self.tmp.name) / "none")
        self.cet6_patch.start()
        self.addCleanup(self.cet6_patch.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_queue_requires_token(self):
        self.assertEqual(
            self.client.get("/api/cet6/drill/queue").status_code, 403)

    def test_queue_returns_note_and_coverage(self):
        response = self.client.get(
            "/api/cet6/drill/queue", params={"limit": 4}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data["count"], 1)
        self.assertNotIn("note", data["items"][0])

    def test_attempt_and_stats(self):
        response = self.client.post("/api/cet6/drill/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section C 讲座/讲话",
            "item": "Recording 1", "sentence": 1,
            "answer": "For 6 years, cells divide forever.", "duration_s": 12})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLess(data["score"], 1.0)
        self.assertGreaterEqual(data["cards_created"], 1)
        self.assertTrue(any(part["miss"] for part in data["parts"]))

        stats = self.client.get(
            "/api/cet6/drill/stats", headers=AUTH).json()
        self.assertEqual(stats["total_attempts"], 1)
        self.assertEqual(stats["sentences"], 1)

    def test_listening_card_enters_review_queue(self):
        self.client.post("/api/cet6/drill/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section C 讲座/讲话",
            "item": "Recording 1", "sentence": 1,
            "answer": "For 6 years, cells divide forever."})
        conn = self._orig(self.db_path)
        conn.execute("UPDATE review_state SET due = date('now') "
                     "WHERE item_type = 'wrong'")
        conn.commit()
        conn.close()
        data = self.client.get(
            "/api/cet6/train/errors", params={"status": "due"},
            headers=AUTH).json()
        self.assertGreaterEqual(data["by_source"].get("cet6_dictation", 0), 1)
        self.assertIn("audio_url", data["items"][0])

    def test_attempt_unknown_sentence_returns_404(self):
        response = self.client.post("/api/cet6/drill/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section C 讲座/讲话",
            "item": "Recording 1", "sentence": 99, "answer": "x"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
