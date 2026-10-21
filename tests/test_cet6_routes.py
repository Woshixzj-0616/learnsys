# -*- coding: utf-8 -*-
"""六级新接口：分析任务、轮询、取消、翻译、runs、令牌。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}
PAYLOAD = {"summary": "连读是主要问题", "patterns": [], "priority": [], "plan": []}


def fake_run(request, cfg=None, abort=None, **_kwargs):
    yield AgentEvent("done", data={
        "text": json.dumps(PAYLOAD, ensure_ascii=False),
        "usage": {"input_tokens": 8, "output_tokens": 3}})


class Cet6RoutesTest(unittest.TestCase):
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
        self.patch_run = mock.patch(
            "learnsys.services.analysis.agent.run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)
        self.client = TestClient(create_app(token=TOKEN))
        self.record = {
            "paper_id": "p1", "paper": "测试卷", "section": "Section A",
            "item": "C1", "scope": "item",
            "sentences": [{"sentence": 3, "en": "make out", "tags": ["连读"],
                           "note": "", "loops": 4, "plays": 6}],
        }

    def test_analysis_requires_token(self):
        self.assertEqual(
            self.client.post("/api/cet6/analysis", json=self.record).status_code, 403)

    def test_analysis_submit_poll_and_latest(self):
        submitted = self.client.post(
            "/api/cet6/analysis", json=self.record, headers=AUTH)
        self.assertEqual(submitted.status_code, 202)
        rid = submitted.json()["id"]
        for _ in range(100):
            row = self.client.get(
                f"/api/cet6/analysis/{rid}", headers=AUTH).json()
            if row["status"] not in ("pending", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["content"]["summary"], "连读是主要问题")
        self.assertEqual(row["tokens_in"], 8)

        latest = self.client.get("/api/cet6/analysis", headers=AUTH, params={
            "paper_id": "p1", "section": "Section A", "item": "C1"}).json()
        self.assertEqual(latest["id"], rid)
        self.assertEqual(latest["status"], "done")

    def test_latest_none(self):
        latest = self.client.get("/api/cet6/analysis", headers=AUTH, params={
            "paper_id": "p1", "section": "Section A", "item": "C1"}).json()
        self.assertEqual(latest["status"], "none")

    def test_analysis_400_when_empty(self):
        bad = dict(self.record, sentences=[])
        res = self.client.post("/api/cet6/analysis", json=bad, headers=AUTH)
        self.assertEqual(res.status_code, 400)

    def test_translate_endpoint(self):
        def fake_translate(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("done", data={"text": json.dumps(
                {"translation": "子网划分", "meaning": "划分子网", "phonetic": ""},
                ensure_ascii=False)})

        with mock.patch("learnsys.services.translate.agent.run", fake_translate):
            res = self.client.post(
                "/api/cet6/translate",
                json={"text": "subnetting", "kind": "word"}, headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["translation"], "子网划分")

    def test_runs_endpoint(self):
        self.client.post("/api/cet6/analysis", json=self.record, headers=AUTH)
        res = self.client.get("/api/runs", headers=AUTH).json()
        self.assertIn("items", res)

    def test_404_for_missing_analysis(self):
        self.assertEqual(
            self.client.get("/api/cet6/analysis/999", headers=AUTH).status_code, 404)

    def test_cancel_unknown_is_false(self):
        res = self.client.post("/api/cet6/analysis/999/cancel", headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
