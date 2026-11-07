# -*- coding: utf-8 -*-
"""本机文件索引接口：状态、重建、令牌。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app
from learnsys.services import local_index

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class LocalIndexRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.root = self.base / "资料"
        self.root.mkdir()
        (self.root / "笔记.md").write_text("# 笔记", encoding="utf-8")
        (self.root / "课件.txt").write_text("正文", encoding="utf-8")

        self.db_path = self.base / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.user = mock.patch.object(
            config, "USER", {"materials": {"import_dirs": [str(self.root)]}})
        self.user.start()
        self.addCleanup(self.user.stop)

        self.client = TestClient(create_app(token=TOKEN))

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/local-index").status_code, 403)

    def test_status_reports_pending_then_indexed(self):
        first = self.client.get("/api/local-index", headers=AUTH)
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(body["roots"][0]["status"], "pending")

        local_index.reconcile(self.root)
        second = self.client.get("/api/local-index", headers=AUTH).json()
        self.assertFalse(second["scanning"])
        self.assertEqual(second["total"], 2)
        self.assertEqual(second["roots"][0]["status"], "ok")
        self.assertEqual(second["roots"][0]["file_count"], 2)

    def test_rebuild_returns_ok(self):
        response = self.client.post("/api/local-index/rebuild", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
