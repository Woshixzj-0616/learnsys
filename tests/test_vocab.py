# -*- coding: utf-8 -*-
"""P13 生词统一表：去重、补空、搜索、改、删、导入、CSV。"""
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


class VocabStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_add_dedupes_case_insensitively_and_fills_empty(self):
        first, created = store.add_vocab(
            self.conn, word="Market", context="the market for used cars")
        self.assertTrue(created)
        second, created_again = store.add_vocab(
            self.conn, word="market", meaning="市场", phonetic="/ˈmɑːkɪt/")
        self.assertFalse(created_again)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["meaning"], "市场")
        self.assertEqual(second["phonetic"], "/ˈmɑːkɪt/")
        self.assertEqual(second["context"], "the market for used cars")
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM vocab_items").fetchone()[0], 1)

    def test_add_does_not_overwrite_existing_meaning(self):
        store.add_vocab(self.conn, word="rent", meaning="租金")
        item, _ = store.add_vocab(self.conn, word="rent", meaning="租用")
        self.assertEqual(item["meaning"], "租金")

    def test_list_search_and_count(self):
        store.add_vocab(self.conn, word="rent", meaning="租金", paper_title="卷三")
        store.add_vocab(self.conn, word="deposit", meaning="押金", paper_title="卷三")
        result = store.list_vocab(self.conn)
        self.assertEqual(result["count"], 2)
        hit = store.list_vocab(self.conn, query="押")
        self.assertEqual([row["word"] for row in hit["items"]], ["deposit"])

    def test_update_and_archive_hides(self):
        item, _ = store.add_vocab(self.conn, word="lease", meaning="租约")
        store.update_vocab(self.conn, item["id"], meaning="租约；租赁",
                           status="archived")
        self.assertEqual(store.list_vocab(self.conn)["count"], 0)
        archived = store.list_vocab(self.conn, status="archived")
        self.assertEqual(archived["items"][0]["meaning"], "租约；租赁")

    def test_delete(self):
        item, _ = store.add_vocab(self.conn, word="tenant")
        self.assertTrue(store.delete_vocab(self.conn, item["id"]))
        self.assertFalse(store.delete_vocab(self.conn, item["id"]))
        self.assertEqual(store.list_vocab(self.conn)["count"], 0)
        self.assertIsNone(store.get_review_state(self.conn, "vocab", item["id"]))

    def test_add_creates_review_state_due_tomorrow(self):
        item, _ = store.add_vocab(self.conn, word="lease")
        state = store.get_review_state(self.conn, "vocab", item["id"])
        self.assertIsNotNone(state)
        expected = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.assertEqual(state["due"], expected)
        self.assertEqual(state["state"], "new")
        listed = store.list_vocab(self.conn)["items"][0]
        self.assertEqual(listed["next_review"], expected)
        self.assertEqual(listed["review_state"], "new")

    def test_import_old_localstorage_shape_is_idempotent(self):
        rows = [
            {"word": "rent", "meaning": "租金", "context": "pay rent",
             "paper": "卷三", "at": "2026-10-20T10:00:00.000Z"},
            {"word": "Deposit", "meaning": "押金", "context": "", "paper": "卷一"},
        ]
        first = store.import_vocab(self.conn, rows)
        second = store.import_vocab(self.conn, rows)
        self.assertEqual(first, {"added": 2, "merged": 0})
        self.assertEqual(second, {"added": 0, "merged": 2})
        self.assertEqual(store.list_vocab(self.conn)["count"], 2)


class VocabRoutesTest(unittest.TestCase):
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

    def test_token_required(self):
        self.assertEqual(self.client.get("/api/vocab").status_code, 403)
        self.assertEqual(
            self.client.post("/api/vocab", json={"word": "rent"}).status_code, 403)

    def test_crud_roundtrip(self):
        created = self.client.post(
            "/api/vocab", json={"word": "market", "meaning": "市场",
                                "context": "the market for used cars"},
            headers=AUTH)
        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertTrue(body["created"])
        item_id = body["item"]["id"]

        again = self.client.post(
            "/api/vocab", json={"word": "Market", "phonetic": "/ˈmɑːkɪt/"},
            headers=AUTH).json()
        self.assertFalse(again["created"])

        listed = self.client.get("/api/vocab?query=市场", headers=AUTH).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["phonetic"], "/ˈmɑːkɪt/")

        patched = self.client.patch(
            f"/api/vocab/{item_id}", json={"meaning": "市场；行情"}, headers=AUTH)
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["item"]["meaning"], "市场；行情")

        deleted = self.client.delete(f"/api/vocab/{item_id}", headers=AUTH)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get("/api/vocab", headers=AUTH).json()["count"], 0)

    def test_import_endpoint(self):
        payload = {"items": [
            {"word": "rent", "meaning": "租金", "paper": "卷三"},
            {"word": "deposit", "meaning": "押金"},
        ]}
        first = self.client.post("/api/vocab/import", json=payload, headers=AUTH)
        self.assertEqual(first.json(), {"added": 2, "merged": 0})
        second = self.client.post("/api/vocab/import", json=payload, headers=AUTH)
        self.assertEqual(second.json(), {"added": 0, "merged": 2})

    def test_csv_has_bom_and_header(self):
        self.client.post(
            "/api/vocab", json={"word": "rent", "meaning": "租金",
                                "paper_title": "卷三"}, headers=AUTH)
        response = self.client.get("/api/vocab/export.csv", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        text = response.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))
        self.assertIn("单词,释义,音标,上下文,试卷,加入时间", text)
        self.assertIn("rent,租金", text)


if __name__ == "__main__":
    unittest.main()
