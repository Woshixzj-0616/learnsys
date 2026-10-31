# -*- coding: utf-8 -*-
"""每日积累接口：令牌、当天内容、状态、生词、往期、今日页摘要。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class DailyRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        conn = store.connect(self.db_path)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="卷一",
            section="Section A 长对话", item="Conversation 1",
            rows=[{"sentence": 1, "en": "He had to combat the problem.",
                   "note": "combat没有听出，听成come back了"}], done=[])
        conn.close()

        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.cet6_patch = mock.patch.object(
            config, "cet6_dir", return_value=self.root / "none")
        self.cet6_patch.start()
        self.addCleanup(self.cet6_patch.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/daily").status_code, 403)

    def test_today_returns_three_sections(self):
        response = self.client.get("/api/daily", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]["writing"]), 2)
        self.assertEqual(len(data["items"]["translation"]), 8)
        self.assertEqual(len(data["items"]["pron"]), 1)
        self.assertEqual(data["items"]["pron"][0]["payload"]["target"], "combat")
        self.assertEqual(data["items"]["pron"][0]["payload"]["heard_as"], "come back")

    def test_mark_status_and_progress(self):
        data = self.client.get("/api/daily", headers=AUTH).json()
        item = data["items"]["writing"][0]
        response = self.client.post(
            f"/api/daily/item/{item['id']}/status", headers=AUTH,
            json={"status": "read"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["done"], 1)

    def test_read_all(self):
        before = self.client.get("/api/daily", headers=AUTH).json()
        response = self.client.post("/api/daily/read-all", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["done"], before["total"])

    def test_term_to_vocab(self):
        data = self.client.get("/api/daily", headers=AUTH).json()
        item = data["items"]["translation"][0]
        response = self.client.post(
            f"/api/daily/term/{item['id']}/vocab", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("vocab", response.json())

    def test_history(self):
        self.client.get("/api/daily", headers=AUTH)
        response = self.client.get("/api/daily/history", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["days"])

    def test_today_payload_has_daily(self):
        response = self.client.get("/api/today", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        daily = response.json()["daily"]
        self.assertEqual(daily["counts"]["writing"]["total"], 2)
        self.assertEqual(daily["counts"]["translation"]["total"], 8)


if __name__ == "__main__":
    unittest.main()
