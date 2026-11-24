# -*- coding: utf-8 -*-
"""P35.3：问答反馈接口与 qa_feedback 落库。"""
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


class QAFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        store.add_agent_run(conn, run_id="run-1", question="测试问题")
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_feedback_is_saved(self):
        res = self.client.post("/api/agent/qa_feedback", headers=AUTH, json={
            "run_id": "run-1", "verdict": "off", "note": "答偏了"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        conn = store.connect(self.db_path)
        try:
            rows = store.list_qa_feedback(conn, "run-1")
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "off")
        self.assertEqual(rows[0]["note"], "答偏了")

    def test_unknown_run_is_404(self):
        res = self.client.post("/api/agent/qa_feedback", headers=AUTH, json={
            "run_id": "missing", "verdict": "ok"})
        self.assertEqual(res.status_code, 404)

    def test_unknown_verdict_is_400(self):
        res = self.client.post("/api/agent/qa_feedback", headers=AUTH, json={
            "run_id": "run-1", "verdict": "bad"})
        self.assertEqual(res.status_code, 400)

    def test_requires_token(self):
        res = self.client.post("/api/agent/qa_feedback", json={
            "run_id": "run-1", "verdict": "ok"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
