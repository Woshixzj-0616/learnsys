# -*- coding: utf-8 -*-
"""六级逐句进度：幂等 upsert、done 语义、按段读取、汇总、事件去重。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class ProgressStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def test_upsert_is_idempotent_and_done_can_be_cleared(self):
        rows = [{"sentence": 1, "en": "hello", "tags": ["生词"], "note": "",
                 "loops": 2, "plays": 3}]
        self.assertEqual(store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="卷一", section="Section A",
            item="C1", rows=rows, done=[1]), 1)
        self.assertEqual(store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="卷一", section="Section A",
            item="C1", rows=rows, done=[1]), 1)
        got = store.cet6_progress_item(
            self.conn, paper_id="p1", section="Section A", item="C1")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["tags"], ["生词"])
        self.assertTrue(got[0]["done"])
        # 不传 done 时保留原值
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="卷一", section="Section A",
            item="C1", rows=rows)
        self.assertTrue(store.cet6_progress_item(
            self.conn, paper_id="p1", section="Section A", item="C1")[0]["done"])
        # 传完整空列表时允许取消完成
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="卷一", section="Section A",
            item="C1", rows=rows, done=[])
        self.assertFalse(store.cet6_progress_item(
            self.conn, paper_id="p1", section="Section A", item="C1")[0]["done"])

    def test_summary(self):
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title="卷一", section="Section A",
            item="C1", rows=[
                {"sentence": 1, "en": "a", "tags": ["生词"]},
                {"sentence": 2, "en": "b", "tags": []},
            ], done=[1])
        summary = store.cet6_progress_summary(self.conn, "p1")
        self.assertEqual(summary[0]["sentences"], 2)
        self.assertEqual(summary[0]["done"], 1)
        self.assertEqual(summary[0]["breakpoints"], 1)


class SyncRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))
        self.payload = {
            "paper": "测试卷", "paper_id": "p1", "section": "Section A",
            "item": "C1", "done": [1],
            "sentences": [
                {"sentence": 1, "en": "hello", "tags": ["生词"], "note": "",
                 "loops": 2, "plays": 3},
                {"sentence": 2, "en": "world", "tags": [], "note": "",
                 "loops": 0, "plays": 1},
            ],
        }

    def test_sync_upserts_progress_and_dedupes_events(self):
        first = self.client.post("/api/cet6/sync", json=self.payload).json()
        second = self.client.post("/api/cet6/sync", json=self.payload).json()
        self.assertEqual(first["count"], 1, "只有带标签/笔记/循环的句子进时间线")
        self.assertEqual(second["count"], 0, "同样的断点不该重复进时间线")

        context = self.client.get(
            "/api/cet6/context", headers=AUTH,
            params={"paper_id": "p1", "section": "Section A", "item": "C1"}).json()
        self.assertEqual(len(context["sentences"]), 2)
        self.assertTrue(context["sentences"][0]["done"])
        self.assertEqual(context["sentences"][0]["tags"], ["生词"])
        # 旧字段仍在，前端/测试不用改
        self.assertIn("events", context)

    def test_sync_requires_section_and_item(self):
        res = self.client.post("/api/cet6/sync", json={
            "paper": "测试卷", "paper_id": "p1", "sentences": []})
        self.assertEqual(res.status_code, 400)

    def test_context_without_params_keeps_old_shape(self):
        self.client.post("/api/cet6/sync", json=self.payload)
        context = self.client.get("/api/cet6/context", headers=AUTH).json()
        self.assertEqual(len(context["events"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
