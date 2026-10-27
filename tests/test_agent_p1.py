# -*- coding: utf-8 -*-
"""P1 接线：摘要注入、8 轮历史、联网工具只出现在 ask/quickbar。"""
from __future__ import annotations

import unittest

from learnsys.agent import loop, prompts, tools


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

    def test_learning_surfaces_do_not(self):
        for surface in ("cet6", "video"):
            with self.subTest(surface=surface):
                names = self.names("explain", surface)
                self.assertNotIn("web_search", names)
                self.assertNotIn("fetch_url", names)

    def test_quiz_does_not(self):
        names = self.names("quiz", "ask")
        self.assertNotIn("web_search", names)
        self.assertNotIn("fetch_url", names)

    def test_execute_routes_web_search(self):
        from learnsys import agent as agent_pkg
        names = {schema["name"] for schema in agent_pkg.tools.TOOL_SCHEMAS}
        self.assertNotIn("web_search", names)            # 不进全量清单，只按入口追加


if __name__ == "__main__":
    unittest.main()
