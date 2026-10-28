"""本地服务：健康、鉴权、跨源、SSE、检索、六级分析/同步。"""
from __future__ import annotations

import json
import pathlib
import socket
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
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
        # 后台复盘线程按 cfg.data_root 取库：隔离数据根，别让它落到生产库
        self.root_patch = mock.patch.object(
            app_config, "DATA_ROOT", pathlib.Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
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

    def test_chat_persists_agent_run_for_replay(self):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("plan", data={"steps": [
                {"index": 0, "title": "看记录", "tool": "today_summary",
                 "status": "pending"}]})
            yield AgentEvent("tool_start", data={
                "name": "today_summary", "input": {}, "goal": "看记录", "step": 0})
            yield AgentEvent("tool_end", data={
                "name": "today_summary", "preview": "看了今天的学习概况",
                "ok": True, "goal": "看记录", "step": 0})
            yield AgentEvent("check", data={"ok": True, "issues": [], "checked": 1})
            yield AgentEvent("done", data={
                "text": "今天学了二叉树。", "usage": {"input_tokens": 3,
                                                    "output_tokens": 5},
                "steps": 2, "stop_reason": "end_turn"})

        with mock.patch.object(routes_agent.agent, "run", fake_run):
            response = self.client.post(
                "/api/agent/chat", json={"message": "我今天学了什么"}, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn('"run_id"', response.text)

        items = self.client.get("/api/conversations", headers=AUTH).json()["items"]
        detail = self.client.get(
            f"/api/conversations/{items[0]['id']}", headers=AUTH).json()
        run_id = detail["messages"][1]["content"]["run_id"]
        run = self.client.get(f"/api/agent/runs/{run_id}", headers=AUTH).json()
        kinds = [item["kind"] for item in run["trace"]]
        self.assertEqual(kinds, ["plan", "tool_start", "tool_end", "check"])
        self.assertEqual(run["usage"]["output_tokens"], 5)
        self.assertTrue(run["check_ok"])
        listed = self.client.get(
            f"/api/agent/runs?conversation_id={items[0]['id']}",
            headers=AUTH).json()["items"]
        self.assertEqual(listed[0]["id"], run_id)

    def test_confirm_endpoint_allows_and_expires(self):
        import threading
        slot = {"event": threading.Event(), "approved": False}
        routes_agent._CONFIRM["run-x:req-1"] = slot
        self.addCleanup(lambda: routes_agent._CONFIRM.pop("run-x:req-1", None))
        result = self.client.post("/api/agent/confirm", headers=AUTH, json={
            "run_id": "run-x", "request_id": "req-1", "approve": True}).json()
        self.assertTrue(result["approved"])
        self.assertTrue(slot["event"].is_set())
        self.assertTrue(slot["approved"])

        expired = self.client.post("/api/agent/confirm", headers=AUTH, json={
            "run_id": "run-x", "request_id": "not-there", "approve": True})
        self.assertEqual(expired.status_code, 404)
        self.assertIn("过期", expired.json()["detail"])

    def test_agent_stats_aggregates_tools_and_anomalies(self):
        conn = store.connect(self.db_path)
        try:
            store.add_agent_run(
                conn, run_id="ok-run", conversation_id=1, question="正常一轮",
                model="test-model", mode="explain", started_at=store.now(),
                first_ms=100, total_ms=1000, steps=2,
                usage={"input_tokens": 100, "output_tokens": 50},
                trace=[
                    {"kind": "tool_start", "data": {"name": "today_summary"}},
                    {"kind": "tool_end", "data": {"name": "today_summary",
                                                 "ok": True, "ms": 120}},
                    {"kind": "check", "data": {"ok": True, "issues": []}},
                ],
                check_ok=True, tool_count=1, model_calls=2,
                cost=0.001, currency="USD")
            store.add_agent_run(
                conn, run_id="bad-run", conversation_id=2, question="失败一轮",
                model="test-model", mode="explain", started_at=store.now(),
                first_ms=200, total_ms=2000, steps=3, error="模型超时",
                trace=[
                    {"kind": "tool_start", "data": {"name": "today_summary"}},
                    {"kind": "tool_end", "data": {"name": "today_summary",
                                                 "ok": False, "ms": 80}},
                    {"kind": "check", "data": {"ok": False,
                                               "issues": ["资料 #9 没读过"]}},
                ],
                check_ok=False, tool_count=1, model_calls=1,
                error_count=2, cost=0.002, currency="USD")
        finally:
            conn.close()
        stats = self.client.get("/api/agent/stats?days=7", headers=AUTH).json()
        self.assertEqual(stats["runs"], 2)
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["totals"]["completion_tokens"], 50)
        self.assertEqual(stats["totals"]["total_tokens"], 150)
        self.assertAlmostEqual(stats["totals"]["cost"], 0.003)
        tool = stats["by_tool"][0]
        self.assertEqual(tool["name"], "today_summary")
        self.assertEqual(tool["calls"], 2)
        self.assertEqual(tool["failures"], 1)
        self.assertEqual(tool["avg_ms"], 100)
        self.assertEqual(len(stats["anomalies"]), 1)
        self.assertIn("资料 #9", "；".join(stats["anomalies"][0]["issues"]))
        self.assertEqual(stats["by_model"][0]["runs"], 2)

    def test_search_and_today(self):
        found = self.client.get("/api/search?q=二叉树", headers=AUTH).json()["results"]
        self.assertTrue(found)
        today = self.client.get("/api/today", headers=AUTH).json()
        self.assertGreaterEqual(today["ask_count"], 1)

    def test_chat_message_keeps_result_id_reference(self):
        """消息只记结果资产的 id，不复制正文；结果正文留在 service_results。"""
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("done", data={"text": "这是引用结果"})

        with mock.patch.object(routes_agent.agent, "run", fake_run):
            response = self.client.post(
                "/api/agent/chat", headers=AUTH,
                json={"message": "接着上次分析", "result_id": 42})
        self.assertEqual(response.status_code, 200)
        conversations = self.client.get(
            "/api/conversations", headers=AUTH).json()["items"]
        detail = self.client.get(
            f"/api/conversations/{conversations[0]['id']}", headers=AUTH).json()
        user = next(item for item in detail["messages"] if item["role"] == "user")
        self.assertEqual(user["result_id"], 42)
        self.assertNotIn("content_json", user)

    def test_today_actions_are_three_cards_at_most(self):
        """今日页三张行动卡：到期错题 / 昨日六级断点或资料 / 薄弱点去测验。"""
        import datetime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        conn = self._orig_connect(self.db_path)
        conn.execute(
            "INSERT INTO cet6_events (ts, paper_id, paper_title, section, item, sentence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"{yesterday} 20:00:00", "paper-1", "英语六级强化刷题卷三",
             "Conversation 1", "精听", 3))
        conn.commit()
        conn.close()
        conn = self._orig_connect(self.db_path)
        store.add_wrong_item(conn, question="虚拟语气怎么判断", answer="看 if 从句时态")
        conn.close()

        actions = self.client.get("/api/today", headers=AUTH).json()["actions"]
        self.assertLessEqual(len(actions), 3)
        kinds = [item["kind"] for item in actions]
        self.assertIn("cet6", kinds, actions)
        self.assertIn("weak", kinds, actions)
        cet6 = next(item for item in actions if item["kind"] == "cet6")
        self.assertIn("paper-1", cet6["href"])
        self.assertTrue(cet6["detail"])

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
