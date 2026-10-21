# -*- coding: utf-8 -*-
"""P15 MCP 只读服务：协议、工具清单、参数与调用路径。"""
from __future__ import annotations

import json
import unittest

from learnsys import mcp_server


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path):
        self.calls.append(("GET", path, None))
        if path == "/api/overview":
            return {"today": {"xp": 30, "goal": 100, "percent": 30},
                    "streak": 2, "week": {}}
        if path == "/api/today":
            return {"date": "2026-10-21", "ask_count": 2,
                    "transcripts": {"count": 1, "chars": 500},
                    "focus": {"minutes": 25, "switches": 3},
                    "cet6": [{"paper": "卷三", "section": "A", "item": "C1",
                              "count": 2}],
                    "due_reviews": 1}
        if path == "/api/review/stats":
            return {"due": 1, "new": 1, "total": 3, "reviewed_today": 2,
                    "next_due": "2026-10-22"}
        if path.startswith("/api/materials?"):
            return {"items": [{"id": 4, "title": "子网课件", "kind": "pdf",
                               "snippet": "子网掩码把 IP 分成网络位和主机位",
                               "page": 3}], "count": 1}
        if path.startswith("/api/materials/4"):
            return {"item": {"id": 4, "title": "子网课件", "chars": 100,
                             "body": "A" * 100}}
        if path.startswith("/api/review/queue"):
            return {"items": [{"item_type": "wrong", "item_id": 7,
                               "question": "什么是子网掩码", "due": "2026-10-21",
                               "state": "new", "reps": 0, "lapses": 0}],
                    "count": 1}
        raise AssertionError("没预料到的路径：" + path)

    def post_json(self, path, body):
        self.calls.append(("POST", path, body))
        if path == "/api/services/translate":
            return {"translation": "市场", "phonetic": "/ˈmɑːkɪt/",
                    "meaning": "市场；行情"}
        raise AssertionError("没预料到的路径：" + path)


class ProtocolTest(unittest.TestCase):
    def test_initialize(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], mcp_server.PROTOCOL_VERSION)
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "learnsys")

    def test_notification_has_no_response(self):
        self.assertIsNone(mcp_server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_has_five_with_annotations(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(names, {"study_context", "search_materials",
                                 "read_material", "due_reviews", "translate"})
        for tool in tools:
            self.assertIn("inputSchema", tool)
            self.assertIn("description", tool)
        read_only = {tool["name"]: tool["annotations"]["readOnlyHint"]
                     for tool in tools}
        self.assertFalse(read_only["translate"])
        self.assertTrue(read_only["study_context"])

    def test_unknown_method(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_bad_json_line(self):
        self.assertIn("-32700", mcp_server.handle_line("{not json"))

    def test_unknown_tool(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "nope", "arguments": {}}},
            FakeClient())
        self.assertEqual(response["error"]["code"], -32602)

    def test_missing_argument(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "search_materials", "arguments": {}}},
            FakeClient())
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("query", response["error"]["message"])


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()

    def call(self, name, arguments=None):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": name, "arguments": arguments or {}}},
            self.client)
        return response["result"]

    def test_study_context(self):
        result = self.call("study_context")
        text = result["content"][0]["text"]
        self.assertIn("30 / 100", text)
        self.assertIn("连续 2 天", text)
        self.assertIn("待复习 1", text)
        self.assertFalse(result["isError"])

    def test_search_materials(self):
        result = self.call("search_materials", {"query": "子网"})
        text = result["content"][0]["text"]
        self.assertIn("子网课件", text)
        self.assertIn("第 3 页", text)
        self.assertIn("/api/materials?q=", self.client.calls[0][1])

    def test_read_material_slices(self):
        result = self.call("read_material",
                           {"material_id": 4, "offset": 10, "limit": 20})
        text = result["content"][0]["text"]
        self.assertIn("子网课件", text)
        self.assertIn("第 11–30 字", text)
        self.assertIn("A" * 20, text)

    def test_due_reviews(self):
        result = self.call("due_reviews", {"limit": 5})
        text = result["content"][0]["text"]
        self.assertIn("什么是子网掩码", text)
        self.assertIn("2026-10-21", text)

    def test_due_reviews_empty(self):
        self.client.get_json = lambda path: {"items": [], "count": 0}
        result = self.call("due_reviews")
        self.assertIn("没有到期", result["content"][0]["text"])

    def test_translate_posts(self):
        result = self.call("translate", {"text": "market"})
        text = result["content"][0]["text"]
        self.assertIn("市场", text)
        method, path, body = self.client.calls[0]
        self.assertEqual((method, path), ("POST", "/api/services/translate"))
        self.assertEqual(body["text"], "market")
        self.assertEqual(body["kind"], "word")

    def test_translate_bad_kind(self):
        response = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "translate",
                        "arguments": {"text": "x", "kind": "bad"}}},
            self.client)
        self.assertEqual(response["error"]["code"], -32602)

    def test_backend_error_becomes_tool_error(self):
        def boom(path):
            raise mcp_server.BackendError("后台没有响应，先启动学习工作台。")
        self.client.get_json = boom
        result = self.call("due_reviews")
        self.assertTrue(result["isError"])
        self.assertIn("先启动学习工作台", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
