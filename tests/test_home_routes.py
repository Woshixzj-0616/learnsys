# -*- coding: utf-8 -*-
"""P27.1 接口：鉴权、返回形状、CRUD 与错误码（路由层不写 SQL）。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server import app as server_app

TOKEN = "home-test-token"


class TestHomeRoutes(unittest.TestCase):
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

    def test_home_requires_token_and_returns_three_domains(self):
        self.assertEqual(self.client.get("/api/home").status_code, 403)
        response = self.client.get("/api/home", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"date", "learning", "work", "life"})
        self.assertIn("done", data["learning"])
        self.assertIn("projects", data["work"])
        self.assertIn("cards", data["life"])

    def test_profile_facts_lifecycle(self):
        created = self.client.post(
            "/api/profile/facts", headers=self.headers,
            json={"kind": "preference", "content": "回答用中文",
                  "evidence": "2026-10-29", "confidence": 0.9})
        self.assertEqual(created.status_code, 200)
        fact = created.json()
        self.assertGreater(fact["id"], 0)
        self.assertEqual(fact["status"], "active")

        listed = self.client.get("/api/profile/facts?kind=preference",
                                 headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["content"], "回答用中文")

        archived = self.client.post(
            f"/api/profile/facts/{fact['id']}/archive", headers=self.headers)
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(
            self.client.get("/api/profile/facts", headers=self.headers)
            .json()["count"], 0)
        self.assertEqual(
            self.client.post("/api/profile/facts/99999/archive",
                             headers=self.headers).status_code, 404)

    def test_profile_facts_validation_is_chinese_400(self):
        empty = self.client.post("/api/profile/facts", headers=self.headers,
                                 json={"content": ""})
        self.assertEqual(empty.status_code, 400)
        self.assertIn("内容", empty.json()["detail"])
        bad_kind = self.client.post(
            "/api/profile/facts", headers=self.headers,
            json={"kind": "unknown", "content": "x"})
        self.assertEqual(bad_kind.status_code, 400)
        self.assertIn("类型", bad_kind.json()["detail"])

    def test_projects_upsert_and_list(self):
        first = self.client.post(
            "/api/projects", headers=self.headers,
            json={"name": "学习工作台", "repo_path": "D:/Desktop/learnsys",
                  "next_step": "完成 P27.1"})
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            "/api/projects", headers=self.headers,
            json={"name": "学习工作台", "repo_path": "D:/Desktop/learnsys",
                  "next_step": "做 P27.2"})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])

        listed = self.client.get("/api/projects", headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["next_step"], "做 P27.2")
        bad = self.client.post("/api/projects", headers=self.headers,
                               json={"name": "", "status": "active"})
        self.assertEqual(bad.status_code, 400)

    def test_subscriptions_upsert_list_and_run(self):
        created = self.client.post(
            "/api/subscriptions", headers=self.headers,
            json={"topic": "AI 新闻", "kind": "news", "cadence": "daily",
                  "at_time": "07:30", "sources": ["https://example.com/rss"]})
        self.assertEqual(created.status_code, 200)
        sub = created.json()
        self.assertEqual(sub["sources"], ["https://example.com/rss"])

        again = self.client.post(
            "/api/subscriptions", headers=self.headers,
            json={"topic": "AI 新闻", "kind": "news", "cadence": "weekly",
                  "at_time": "08:00"})
        self.assertEqual(again.json()["id"], sub["id"])
        listed = self.client.get("/api/subscriptions", headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["cadence"], "weekly")

        # P30.1 起 run 会真的生成卡片；当天简报还没生成时新闻订阅返回 400，不空转。
        ran = self.client.post(f"/api/subscriptions/{sub['id']}/run",
                               headers=self.headers)
        self.assertEqual(ran.status_code, 400)
        self.assertIn("简报", ran.json()["detail"])
        self.assertEqual(
            self.client.post("/api/subscriptions/99999/run",
                             headers=self.headers).status_code, 404)
        bad = self.client.post(
            "/api/subscriptions", headers=self.headers,
            json={"topic": "x", "cadence": "hourly"})
        self.assertEqual(bad.status_code, 400)

    def test_home_accepts_optional_day(self):
        response = self.client.get("/api/home?day=2026-10-29",
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["date"], "2026-10-29")


if __name__ == "__main__":
    unittest.main()
