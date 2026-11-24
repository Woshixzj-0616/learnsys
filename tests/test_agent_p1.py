# -*- coding: utf-8 -*-
"""P1 接线：摘要注入、8 轮历史、联网工具只出现在 ask/quickbar。"""
from __future__ import annotations

import datetime
import unittest
from unittest import mock

from learnsys.agent import loop, prompts, tools
from learnsys.agent.tools import web_tools


class PromptSummaryTest(unittest.TestCase):
    def test_summary_injected(self):
        system = prompts.build_system("explain", summary="用户在学二叉树。")
        self.assertIn("本会话摘要", system)
        self.assertIn("用户在学二叉树", system)

    def test_empty_summary_not_injected(self):
        self.assertNotIn("本会话摘要", prompts.build_system("explain"))

    def test_history_window_eight_turns(self):
        history = [(f"问题{i}", f"回答{i}") for i in range(10)]
        messages = loop._history_messages(history, "")
        self.assertEqual(len(messages), 16)              # 8 轮 × 2 条
        self.assertEqual(messages[0]["content"][0]["text"], "问题0")
        self.assertEqual(messages[2]["content"][0]["text"], "问题3")
        self.assertEqual(messages[-2]["content"][0]["text"], "问题9")


class WebToolSurfaceTest(unittest.TestCase):
    def names(self, mode: str, surface: str) -> set[str]:
        return {schema["name"] for schema in tools.schemas_for(
            mode, use_tools=True, surface=surface)}

    def test_ask_and_quickbar_have_web_tools(self):
        for surface in ("ask", "quickbar"):
            with self.subTest(surface=surface):
                names = self.names("explain", surface)
                self.assertIn("web_search", names)
                self.assertIn("fetch_url", names)

    def test_video_surface_does_not(self):
        names = self.names("explain", "video")
        self.assertNotIn("web_search", names)
        self.assertNotIn("fetch_url", names)

    def test_cet6_now_uses_assistant_tools(self):
        # P35.3：CET6 只是外部 App，不再有专属工具裁剪，联网工具随 assistant 白名单。
        names = self.names("explain", "cet6")
        self.assertIn("web_search", names)
        self.assertIn("fetch_url", names)

    def test_quiz_does_not(self):
        names = self.names("quiz", "ask")
        self.assertNotIn("web_search", names)
        self.assertNotIn("fetch_url", names)

    def test_execute_routes_web_search(self):
        from learnsys import agent as agent_pkg
        names = {schema["name"] for schema in agent_pkg.tools.TOOL_SCHEMAS}
        self.assertNotIn("web_search", names)            # 不进全量清单，只按入口追加


class WebToolReadDateTest(unittest.TestCase):
    """§12 网页引用：工具必须把「读取日期」交给模型，日期才有唯一来源。"""

    def test_search_output_carries_read_date(self):
        payload = {"query": "python", "results": [{
            "title": "Python", "url": "https://www.python.org/downloads/",
            "snippet": "下载", "date": "2026-10-01"}]}
        with mock.patch.object(web_tools.web, "web_search", return_value=payload):
            text = web_tools.web_search("python")
        self.assertIn(f"读取日期（{datetime.date.today().isoformat()}）", text)

    def test_fetch_output_carries_read_date(self):
        page = {"title": "Python", "text": "正文",
                "final_url": "https://www.python.org/downloads/"}
        with mock.patch.object(web_tools.web, "fetch_page", return_value=page):
            text = web_tools.fetch_url("https://www.python.org/downloads/")
        self.assertIn(f"读取日期：{datetime.date.today().isoformat()}", text)


if __name__ == "__main__":
    unittest.main()
