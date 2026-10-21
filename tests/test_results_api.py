# -*- coding: utf-8 -*-
"""P13 通用结果资产接口：按 id / 条件读 service_results。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class ResultsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        self.result_id = conn.execute(
            "INSERT INTO service_results "
            "(kind, target_type, target_id, scope, context_hash, prompt_version, "
            " model, status, input_json, content_json, tokens_in, tokens_out, "
            " cache_hit, ms, created_at, updated_at) "
            "VALUES ('cet6_analyze', 'item', 'p1/A/C1', 'item', 'h1', 'v1', "
            " 'deepseek-flash', 'done', ?, ?, 10, 20, 0, 900, ?, ?)",
            (json.dumps({"secret": "不该出现在响应里"}, ensure_ascii=False),
             json.dumps({"summary": "连读是主要问题"}, ensure_ascii=False),
             "2026-10-21 10:00:00", "2026-10-21 10:00:05")).lastrowid
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
        self.assertEqual(
            self.client.get(f"/api/results/{self.result_id}").status_code, 403)

    def test_get_by_id_hides_input(self):
        response = self.client.get(
            f"/api/results/{self.result_id}", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], self.result_id)
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["content"]["summary"], "连读是主要问题")
        self.assertNotIn("input_json", body)
        self.assertNotIn("secret", json.dumps(body, ensure_ascii=False))
        self.assertEqual(body["cache_hit"], 0)

    def test_get_missing_returns_404(self):
        self.assertEqual(
            self.client.get("/api/results/99999", headers=AUTH).status_code, 404)

    def test_list_filters_and_count(self):
        listed = self.client.get(
            "/api/results?kind=cet6_analyze&target_id=p1/A/C1", headers=AUTH)
        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["id"], self.result_id)
        self.assertEqual(
            self.client.get("/api/results?kind=other", headers=AUTH).json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
