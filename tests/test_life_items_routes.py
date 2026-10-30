# -*- coding: utf-8 -*-
"""P30.2 接口：事务箱 CRUD/状态动作，卡片接口迁移后仍可用。"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server import app as server_app

TOKEN = "life-items-token"


class TestLifeItemsRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.db = root / "learning.db"
        store.connect(self.db).close()
        self.orig = store.connect
        patches = [
            mock.patch.object(
                store, "connect",
                side_effect=lambda path=None: self.orig(path or self.db)),
            mock.patch.object(app_config, "DATA_ROOT", root / "data"),
            mock.patch.object(app_config, "SETTINGS_FILE", root / "设置.json"),
            mock.patch.object(app_config, "USER", {}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server_app.create_app(token=TOKEN))
        self.headers = {"X-Learnsys-Token": TOKEN}
        self.day = dt.date.today().isoformat()

    def _create(self, **payload):
        data = {"title": "交房租", "kind": "todo", "due_date": self.day}
        data.update(payload)
        response = self.client.post("/api/life/items", headers=self.headers,
                                    json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_list_and_counts(self):
        self._create()
        self._create(title="07:10 起床", kind="habit", value="07:10 起床",
                     due_date="")
        listed = self.client.get("/api/life/items", headers=self.headers).json()
        self.assertEqual(listed["count"], 2)
        titles = [item["title"] for item in listed["items"]]
        self.assertIn("交房租", titles)
        self.assertIn("07:10 起床", titles)

    def test_done_reopen_archive(self):
        item = self._create()
        done = self.client.post(f"/api/life/items/{item['id']}/done",
                                headers=self.headers)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["status"], "done")
        self.assertTrue(done.json()["done_at"])
        self.assertEqual(
            self.client.get("/api/life/items", headers=self.headers)
            .json()["count"], 0)
        self.assertEqual(
            self.client.get("/api/life/items?status=done", headers=self.headers)
            .json()["count"], 1)

        reopened = self.client.post(f"/api/life/items/{item['id']}/reopen",
                                    headers=self.headers)
        self.assertEqual(reopened.json()["status"], "open")
        archived = self.client.post(f"/api/life/items/{item['id']}/archive",
                                    headers=self.headers)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(
            self.client.get("/api/life/items?status=archived",
                            headers=self.headers).json()["count"], 1)

    def test_patch_and_delete(self):
        item = self._create()
        patched = self.client.patch(f"/api/life/items/{item['id']}",
                                    headers=self.headers,
                                    json={"title": "交水电费", "note": "线上"})
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["title"], "交水电费")
        self.assertEqual(patched.json()["note"], "线上")
        deleted = self.client.delete(f"/api/life/items/{item['id']}",
                                     headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get("/api/life/items", headers=self.headers)
            .json()["count"], 0)

    def test_validation_is_chinese_400(self):
        empty = self.client.post("/api/life/items", headers=self.headers,
                                 json={"title": ""})
        self.assertEqual(empty.status_code, 400)
        self.assertIn("标题", empty.json()["detail"])
        bad_kind = self.client.post("/api/life/items", headers=self.headers,
                                    json={"title": "x", "kind": "meeting"})
        self.assertEqual(bad_kind.status_code, 400)
        bad_due = self.client.post("/api/life/items", headers=self.headers,
                                   json={"title": "x", "due_date": "10-30"})
        self.assertEqual(bad_due.status_code, 400)
        self.assertIn("YYYY-MM-DD", bad_due.json()["detail"])
        self.assertEqual(
            self.client.post("/api/life/items/99999/done",
                             headers=self.headers).status_code, 404)

    def test_cards_endpoints_moved_but_unchanged(self):
        listed = self.client.get("/api/life/cards", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 0)
        self.assertEqual(
            self.client.post("/api/life/cards/99999/read", headers=self.headers,
                             json={"read": True}).status_code, 404)

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/life/items").status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
