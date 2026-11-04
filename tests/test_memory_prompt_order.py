"""系统提示词顺序：摘要 → 画像 → 个人状态 → 长期记忆。"""
from __future__ import annotations

import unittest

from learnsys.agent import prompts


class TestMemoryPromptOrder(unittest.TestCase):
    def test_sections_keep_order(self):
        text = prompts.build_system(
            "explain", summary="会话摘要内容", profile="画像内容",
            personal_state="个人状态内容",
            memories="【用户长期记忆】\n- 记忆内容")
        positions = [
            text.index("会话摘要内容"),
            text.index("画像内容"),
            text.index("个人状态内容"),
            text.index("记忆内容"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_profile_heading_is_generated_not_user_file(self):
        text = prompts.build_system("explain", profile="画像内容")
        self.assertIn("【用户画像（由长期记忆自动编译", text)
        self.assertNotIn("用户自己维护", text)


if __name__ == "__main__":
    unittest.main()
