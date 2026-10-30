# -*- coding: utf-8 -*-
"""P30.1 接口：订阅真正生成、卡片列表/已读、删除、错误码。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server import app as server_app

TOKEN = "life-test-token"


class TestLifeRoutes(unittest.TestCase):
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

    def _create(self, **payload):
        data = {"topic": "每天一句英语", "kind": "custom", "cadence": "daily",
                "at_time": "07:30", "enabled": True}
        data.update(payload)
        response = self.client.post("/api/subscriptions", headers=self.headers,
                                    json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_custom_run_generates_card(self):
        sub = self._create()
        with mock.patch("learnsys.agent.complete",
                        return_value=("Keep going.", "", {})):
            ran = self.client.post(f"/api/subscriptions/{sub['id']}/run",
                                   headers=self.headers)
        self.assertEqual(ran.status_code, 200, ran.text)
        body = ran.json()
        self.assertTrue(body["last_run"])
        self.assertEqual(body["card"]["title"], "每天一句英语")
        self.assertIn("Keep going", body["card"]["content"]["summary"])

        listed = self.client.get("/api/life/cards", headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        self.assertFalse(listed["items"][0]["read"])

    def test_news_run_before_briefing_is_chinese_400(self):
        sub = self._create(topic="AI", kind="news", sources=[])
        ran = self.client.post(f"/api/subscriptions/{sub['id']}/run",
                               headers=self.headers)
        self.assertEqual(ran.status_code, 400)
        self.assertIn("简报", ran.json()["detail"])

    def test_price_run_is_chinese_400(self):
        sub = self._create(topic="金价", kind="price")
        ran = self.client.post(f"/api/subscriptions/{sub['id']}/run",
                               headers=self.headers)
        self.assertEqual(ran.status_code, 400)
        self.assertIn("不支持", ran.json()["detail"])

    def test_mark_card_read(self):
        sub = self._create()
        with mock.patch("learnsys.agent.complete", return_value=("正文", "", {})):
            ran = self.client.post(f"/api/subscriptions/{sub['id']}/run",
                                   headers=self.headers).json()
        card_id = ran["card"]["id"]
        read = self.client.post(f"/api/life/cards/{card_id}/read",
                                headers=self.headers, json={"read": True})
        self.assertEqual(read.status_code, 200)
        self.assertTrue(read.json()["read"])
        unread = self.client.post(f"/api/life/cards/{card_id}/read",
                                  headers=self.headers, json={"read": False})
        self.assertFalse(unread.json()["read"])
        self.assertEqual(
            self.client.post("/api/life/cards/99999/read", headers=self.headers,
                             json={"read": True}).status_code, 404)

    def test_patch_subscription_updates_same_row(self):
        sub = self._create()
        patched = self.client.patch(f"/api/subscriptions/{sub['id']}",
                                    headers=self.headers,
                                    json={"topic": "每日一句", "cadence": "weekly",
                                          "enabled": False})
        self.assertEqual(patched.status_code, 200, patched.text)
        body = patched.json()
        self.assertEqual(body["id"], sub["id"])
        self.assertEqual(body["topic"], "每日一句")
        self.assertEqual(body["cadence"], "weekly")
        self.assertFalse(body["enabled"])
        listed = self.client.get("/api/subscriptions", headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(
            self.client.patch("/api/subscriptions/99999", headers=self.headers,
                              json={"topic": "x"}).status_code, 404)

    def test_delete_subscription(self):
        sub = self._create()
        deleted = self.client.delete(f"/api/subscriptions/{sub['id']}",
                                     headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        listed = self.client.get("/api/subscriptions", headers=self.headers).json()
        self.assertEqual(listed["count"], 0)
        self.assertEqual(
            self.client.delete(f"/api/subscriptions/{sub['id']}",
                               headers=self.headers).status_code, 404)

    def test_missing_subscription_is_404(self):
        self.assertEqual(
            self.client.post("/api/subscriptions/99999/run",
                             headers=self.headers).status_code, 404)

    def test_stock_config_masks_token(self):
        empty = self.client.get("/api/life/stock/config", headers=self.headers)
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.json()["configured"])
        saved = self.client.post("/api/life/stock/config", headers=self.headers,
                                 json={"token": "abcd1234efgh"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["token_tail"], "efgh")
        self.assertTrue(saved.json()["configured"])
        self.assertNotIn("abcd1234efgh", json.dumps(saved.json(), ensure_ascii=False))
        listed = self.client.get("/api/life/stock/config", headers=self.headers)
        self.assertEqual(listed.json()["token_tail"], "efgh")

    def test_cards_require_token(self):
        self.assertEqual(self.client.get("/api/life/cards").status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
