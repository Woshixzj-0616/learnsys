# -*- coding: utf-8 -*-
"""P13 最小服务目录：列出、分派、参数校验。"""
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


class ServicesApiTest(unittest.TestCase):
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
        self.assertEqual(self.client.get("/api/services").status_code, 403)

    def test_catalog_lists_three_services(self):
        body = self.client.get("/api/services", headers=AUTH).json()
        kinds = {item["kind"] for item in body["items"]}
        self.assertEqual(kinds, {"translate", "translate_items", "cet6_analyze"})
        translate = next(item for item in body["items"] if item["kind"] == "translate")
        self.assertEqual(translate["mode"], "sync")
        self.assertIn("text", translate["params"])

    def test_unknown_kind_is_404(self):
        response = self.client.post(
            "/api/services/nope", json={}, headers=AUTH)
        self.assertEqual(response.status_code, 404)

    def test_missing_param_is_400(self):
        response = self.client.post(
            "/api/services/translate", json={}, headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertIn("text", response.json()["detail"])

    def test_translate_dispatches_to_service_layer(self):
        with mock.patch(
                "learnsys.services.translate.translate",
                return_value={"translation": "你好"}) as fake:
            response = self.client.post(
                "/api/services/translate",
                json={"text": "hello", "kind": "word"}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["translation"], "你好")
        fake.assert_called_once()
        self.assertEqual(fake.call_args.args[0], "hello")
        self.assertEqual(fake.call_args.kwargs["kind"], "word")

    def test_analyze_dispatches_to_job_submit(self):
        with mock.patch(
                "learnsys.services.analysis.submit",
                return_value={"id": 7, "status": "pending"}) as fake:
            response = self.client.post(
                "/api/services/cet6_analyze",
                json={"paper_id": "p1", "section": "A", "item": "C1",
                      "sentences": [{"sentence": 1, "en": "hi"}]},
                headers=AUTH)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["id"], 7)
        fake.assert_called_once()
        self.assertEqual(fake.call_args.args[0]["section"], "A")


if __name__ == "__main__":
    unittest.main()
