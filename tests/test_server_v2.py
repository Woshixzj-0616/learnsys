"""本地服务：健康、鉴权、跨源、SSE、检索、六级分析/同步。"""
from __future__ import annotations

import json
import pathlib
import socket
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.server import routes_agent, routes_cet6
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        store.add_ask(conn, "二叉树怎么遍历", "前序、中序、后序", 100, "test")
        conn.close()

        self._orig_connect = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig_connect(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.tmp.cleanup)

        self.app = create_app(token=TOKEN)
        self.client = TestClient(self.app)

    def test_health_and_config(self):
        health = self.client.get("/api/health").json()
        self.assertTrue(health["ok"])
        self.assertEqual(health["token"], TOKEN)
        self.assertEqual(pathlib.Path(health["db"]).name, "learning.db")

        config = self.client.get("/api/config", headers=AUTH).json()
        self.assertIn("ready", config)
        self.assertNotIn("auth_token", config)

    def test_chat_requires_token_and_origin(self):
        self.assertEqual(
            self.client.post("/api/agent/chat", json={"message": "hi"}).status_code, 403)
        bad = self.client.post(
            "/api/agent/chat", json={"message": "hi"},
            headers={**AUTH, "Origin": "http://evil.example"})
        self.assertEqual(bad.status_code, 403)

    def test_chat_sse_persists_conversation(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("text", "你")
            yield AgentEvent("text", "好")
            yield AgentEvent("done", data={"text": "你好"})

        with mock.patch.object(routes_agent.agent, "run", fake_run):
            response = self.client.post(
                "/api/agent/chat", json={"message": "打个招呼"}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn('"kind": "start"', response.text)
        self.assertIn('"kind": "done"', response.text)

        items = self.client.get("/api/conversations", headers=AUTH).json()["items"]
        self.assertEqual(len(items), 1)
        detail = self.client.get(
            f"/api/conversations/{items[0]['id']}", headers=AUTH).json()
        roles = [message["role"] for message in detail["messages"]]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(detail["messages"][1]["content"]["text"], "你好")

    def test_internal_chat_not_counted_as_ask(self):
        """复盘/测验的内部提示词只留会话上下文，不算「我问过什么」。"""
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("done", data={"text": "复盘结果"})

        before = self.client.get("/api/today", headers=AUTH).json()["ask_count"]
        with mock.patch.object(routes_agent.agent, "run", fake_run):
            res = self.client.post("/api/agent/chat", headers=AUTH, json={
                "message": "请帮我复盘今天", "module": "review", "internal": True})
        self.assertEqual(res.status_code, 200)
        after = self.client.get("/api/today", headers=AUTH).json()["ask_count"]
        self.assertEqual(after, before, "internal 提示词被记成问答了")
        self.assertEqual(self.client.get("/api/conversations", headers=AUTH)
                         .json()["items"], [], "复盘会话不该混进问一问列表")
        review_items = self.client.get(
            "/api/conversations?module=review", headers=AUTH).json()["items"]
        self.assertEqual(len(review_items), 1)
        self.assertEqual(review_items[0]["module"], "review")

    def test_search_and_today(self):
        found = self.client.get("/api/search?q=二叉树", headers=AUTH).json()["results"]
        self.assertTrue(found)
        today = self.client.get("/api/today", headers=AUTH).json()
        self.assertGreaterEqual(today["ask_count"], 1)

    def test_wrongbook_toggle(self):
        asks = self.client.get("/api/today", headers=AUTH).json()["asks"]
        ask_id = asks[0]["id"]
        result = self.client.post(
            f"/api/wrongbook/{ask_id}/toggle", headers=AUTH).json()
        self.assertTrue(result["starred"])
        items = self.client.get("/api/wrongbook", headers=AUTH).json()["items"]
        self.assertEqual(len(items), 1)

    def test_cet6_analyze_and_sync(self):
        payload = {
            "summary": "主要问题是连读", "patterns": [], "priority": [], "plan": []
        }

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("done", data={"text": json.dumps(payload, ensure_ascii=False)})

        record = {
            "paper": "测试卷", "section": "Section B", "item": "Conversation 1",
            "scope": "item",
            "sentences": [{"sentence": 3, "en": "make out", "tags": ["连读"],
                           "note": "没听清", "loops": 4, "plays": 6}],
        }
        with mock.patch.object(routes_cet6.agent, "run", fake_run):
            result = self.client.post("/analyze", json=record).json()
        self.assertEqual(result["analysis"]["summary"], "主要问题是连读")

        sync = self.client.post("/api/cet6/sync", json={
            "paper": "测试卷", "paper_id": "p1", "section": "Section B",
            "item": "Conversation 1", "sentences": record["sentences"],
        }).json()
        self.assertEqual(sync["count"], 1)
        context = self.client.get("/api/cet6/context", headers=AUTH).json()
        self.assertEqual(len(context["events"]), 1)

    def test_cet6_import_roundtrip(self):
        """file:// 推上来的 localStorage 快照，HTTP 首开要能原样读回去。"""
        items = {
            "listening_splitter_v1_卷一": '{"done":{"A-1":{"1":true}}}',
            "listening_workbench_vocab_v1": '["rent","deposit"]',
        }
        saved = self.client.post("/api/cet6/import", json={"items": items}).json()
        self.assertEqual(saved["count"], 2)
        restored = self.client.get("/api/cet6/import").json()
        self.assertEqual(restored["items"], items)

    def test_today_cet6_returns_paper_dir_for_deeplink(self):
        """时间线条目要带 paper_id（= 试卷目录名），前端才能 ?paper= 跳回去。"""
        self.client.post("/api/cet6/sync", json={
            "paper": "卷一", "paper_id": "卷一目录", "section": "Section A",
            "item": "Conversation 1",
            "sentences": [{"sentence": 1, "en": "hello", "tags": ["生词"]}],
        })
        today = self.client.get("/api/today", headers=AUTH).json()
        row = next(item for item in today["cet6"] if item["paper"] == "卷一")
        self.assertEqual(row["paper_id"], "卷一目录")


class PortProbeTest(unittest.TestCase):
    def test_port_free_detects_listener_and_closed_port(self):
        """真机坑：没有监听时 connect 可能超时而不是拒绝 —— 必须能判定为空闲。"""
        from learnsys.server.app import port_free
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)
        try:
            self.assertFalse(port_free(port), "已经有人在监听，应判为占用")
        finally:
            srv.close()
        self.assertTrue(port_free(port), "监听关掉后应判为空闲")


if __name__ == "__main__":
    unittest.main()
