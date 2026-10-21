# -*- coding: utf-8 -*-
"""P5 插件化：清单发现、学习点/等级、网工训练事件、插件开关。"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import config as agent_config
from learnsys.modules import load_registry
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class PluginRegistryTest(unittest.TestCase):
    def test_manifests_discovered_and_sorted(self):
        data = load_registry()
        ids = [m["id"] for m in data["modules"]]
        self.assertIn("today", ids)
        self.assertIn("netlab", ids)
        self.assertIn("plugins", ids)
        self.assertEqual(ids[0], "today")
        self.assertEqual(ids[-1], "plugins")
        self.assertLess(ids.index("netlab"), ids.index("cet6"))
        netlab = next(m for m in data["modules"] if m["id"] == "netlab")
        self.assertEqual(netlab["status"], "ready")
        self.assertTrue(netlab["home"])
        self.assertTrue(netlab["tagline"])
        self.assertEqual(data["schema"], 2)

    def test_no_legacy_registry_file_in_source(self):
        from learnsys.modules import plugins_dir
        self.assertTrue(plugins_dir().is_dir())
        self.assertFalse((plugins_dir().parent / "modules" / "registry.json").exists())


class PluginApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data_root = root / "data"
        self.settings_file = root / "设置.json"
        self.db_path = root / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig_connect = store.connect
        patches = [
            mock.patch.object(store, "connect",
                              side_effect=lambda path=None: self._orig_connect(path or self.db_path)),
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "SETTINGS_FILE", self.settings_file),
            mock.patch.object(app_config, "USER", {}),
            mock.patch.object(agent_config, "CLAUDE_SETTINGS", root / "无此文件.json"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(token=TOKEN)
        self.client = TestClient(self.app)

    def _seed(self):
        now = datetime.datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        start = (now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._orig_connect(self.db_path)
        try:
            cur = conn.execute("INSERT INTO sessions (started_at, ended_at) VALUES (?, ?)",
                               (start, stamp))
            sid = int(cur.lastrowid)
            conn.execute("INSERT INTO asks (ts, question, answer, starred) VALUES (?, ?, ?, 1)",
                         (stamp, "什么是子网掩码", "用来划分网络位和主机位"))
            conn.execute(
                "INSERT INTO transcripts (session_id, ts_start, ts_end, text) VALUES (?, ?, ?, ?)",
                (sid, start, stamp, "今天讲了子网划分"))
            conn.execute(
                "INSERT INTO cet6_events (ts, paper_id, paper_title, section, item, sentence, tags) "
                "VALUES (?, '卷一', '测试卷', 'Section A', 'Conversation 1', 1, '连读')",
                (stamp,))
            conn.commit()
        finally:
            conn.close()

    def test_overview_rewards_and_level(self):
        self._seed()
        data = self.client.get("/api/overview", headers=AUTH).json()
        # 问答 10 + 收藏 3 + 转写 5 + 断点 8 + 专注 10 分钟 10 点 = 36
        self.assertEqual(data["today"]["xp"], 36)
        self.assertEqual(data["total"]["xp"], 36)
        self.assertEqual(data["total"]["level"], 1)
        self.assertEqual(data["total"]["title"], "网络小白")
        self.assertEqual(data["streak"], 1)
        self.assertEqual(data["today"]["goal"], 100)
        earned = {a["id"] for a in data["achievements"] if a["earned"]}
        self.assertIn("first_ask", earned)
        self.assertNotIn("streak_3", earned)

    def test_netlab_event_counts_and_xp(self):
        res = self.client.post("/api/events", headers=AUTH, json={
            "module": "netlab", "kind": "drill", "title": "CIDR 速算",
            "meta": {"card": "cidr", "track": "addr"},
        })
        self.assertEqual(res.status_code, 200)
        events = self.client.get("/api/events?module=netlab", headers=AUTH).json()["items"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "CIDR 速算")
        self.assertEqual(events[0]["meta"]["card"], "cidr")
        overview = self.client.get("/api/overview", headers=AUTH).json()
        self.assertEqual(overview["today"]["netlab"], 1)
        self.assertEqual(overview["today"]["xp"], 15)

    def test_study_today_prompts_and_review_quiz_xp(self):
        self._seed()
        data = self.client.get("/api/study/today", headers=AUTH).json()
        self.assertEqual(data["stats"]["cet6"], 1)
        self.assertEqual(data["stats"]["transcripts"], 1)
        self.assertTrue(any("六级精听" in line for line in data["summary_lines"]))
        self.assertIn("请帮我复盘", data["review_prompt"])
        self.assertIn("5 道自测题", data["quiz_prompt"])

        self.client.post("/api/events", headers=AUTH, json={
            "module": "review", "kind": "report", "title": "今日复盘", "meta": {}})
        self.client.post("/api/events", headers=AUTH, json={
            "module": "quiz", "kind": "quiz", "title": "今日测验", "meta": {}})
        overview = self.client.get("/api/overview", headers=AUTH).json()
        # 36（问答/收藏/转写/断点/专注）+ 复盘 25 + 测验 20
        self.assertEqual(overview["today"]["xp"], 81)
        earned = {a["id"] for a in overview["achievements"] if a["earned"]}
        self.assertIn("review_1", earned)
        self.assertIn("quiz_1", earned)

    def test_review_and_quiz_plugins_ready(self):
        modules = self.client.get("/api/modules", headers=AUTH).json()["modules"]
        for pid in ("review", "quiz"):
            mod = next(m for m in modules if m["id"] == pid)
            self.assertEqual(mod["status"], "ready")
            self.assertTrue(mod["home"])

    def test_plugin_toggle_persists(self):
        self.client.post("/api/settings", headers=AUTH, json={"modules": {"netlab": False}})
        settings = self.client.get("/api/settings", headers=AUTH).json()
        self.assertFalse(settings["modules"]["netlab"])
        self.assertTrue(settings["modules"]["ask"])
        # 清单仍是完整的一份，开关只影响前端显示
        modules = self.client.get("/api/plugins", headers=AUTH).json()["modules"]
        self.assertTrue(any(m["id"] == "netlab" for m in modules))

    def test_events_require_token(self):
        res = self.client.post("/api/events", json={"module": "netlab", "title": "x"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
