# -*- coding: utf-8 -*-
"""记忆 API：字段、候选采纳、画像编译、注入审计、档案状态。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app


class MemoryRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db_path = self.root / "learning.db"
        self.orig = store.connect
        patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self.orig(path or self.db_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data_patch = mock.patch.object(config, "DATA_ROOT", self.root)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.client = TestClient(create_app(token="t"))
        self.auth = {"X-Learnsys-Token": "t"}

    def test_add_with_scope_and_confidence(self):
        added = self.client.post("/api/memory", json={
            "content": "听力先看题", "kind": "preference",
            "scope": "exam:cet6", "confidence": 0.8}, headers=self.auth)
        self.assertEqual(added.status_code, 200)
        item = self.client.get("/api/memory", headers=self.auth).json()["items"][0]
        self.assertEqual(item["scope"], "exam:cet6")
        self.assertAlmostEqual(item["confidence"], 0.8)

    def test_candidate_promote(self):
        conn = store.connect(self.db_path)
        try:
            memory_id, _ = store.add_memory(
                conn, "以后先复习再刷新题", status="candidate", confidence=0.6)
        finally:
            conn.close()
        candidates = self.client.get(
            "/api/memory/candidates", headers=self.auth).json()["items"]
        self.assertEqual(candidates[0]["id"], memory_id)
        promoted = self.client.post(
            f"/api/memory/{memory_id}/promote", headers=self.auth)
        self.assertEqual(promoted.status_code, 200)
        self.assertEqual(self.client.get(
            "/api/memory/candidates", headers=self.auth).json()["items"], [])

    def test_profile_compile_and_status(self):
        conn = store.connect(self.db_path)
        try:
            store.add_memory(conn, "网络工程大二", kind="identity")
        finally:
            conn.close()
        compiled = self.client.post(
            "/api/memory/profile/compile", headers=self.auth)
        self.assertEqual(compiled.status_code, 200)
        self.assertEqual(compiled.json()["facts"], 1)
        profile = self.client.get("/api/memory/profile", headers=self.auth).json()
        self.assertIn("网络工程大二", profile["text"])
        self.assertFalse(profile["stale"])

    def test_injections_read_trace(self):
        conn = store.connect(self.db_path)
        try:
            store.add_agent_run(
                conn, run_id="r1", started_at="2026-11-04 10:00:00",
                trace=[{"kind": "memory", "data": {
                    "ids": [1, 2], "chars": 120, "budget": {"items": 12}}}])
        finally:
            conn.close()
        items = self.client.get(
            "/api/memory/injections", headers=self.auth).json()["items"]
        self.assertEqual(items[0]["ids"], [1, 2])

    def test_archive_status_is_readable(self):
        result = self.client.get(
            "/api/memory/archive/status", headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertIn("running", result.json())

    def test_archive_search_without_archive(self):
        result = self.client.get(
            "/api/memory/archive/search", params={"q": "六级"}, headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["items"], [])


if __name__ == "__main__":
    unittest.main()
