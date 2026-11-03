# -*- coding: utf-8 -*-
"""排错提示词注入：只有 ops 才加，速答用一行版。"""
from __future__ import annotations

import unittest

from learnsys.agent import prompt_ops, prompts


class OpsPromptTest(unittest.TestCase):
    def test_ops_rule_injected(self):
        system = prompts.build_system("explain", ops=True)
        self.assertIn("先取证", system)
        self.assertIn("事实分三级", system)
        self.assertIn("凭记忆，未验证", system)
        self.assertIn("不许把候选原因说成根因", system)

    def test_rule_absent_without_ops(self):
        system = prompts.build_system("explain")
        self.assertNotIn("先取证", system)
        self.assertNotIn("本轮是排错", system)

    def test_quick_uses_one_line_rule(self):
        system = prompts.build_system("quick", ops=True)
        self.assertIn(prompt_ops.OPS_QUICK_RULE, system)
        self.assertNotIn(prompt_ops.OPS_DEBUG_RULE, system)

    def test_rewrite_prompt_mentions_issues(self):
        issues = ["unsupported_absolute：根因就是 X"]
        user = prompt_ops.build_rewrite_user("根因就是 X", issues, "（本轮没有工具结果）")
        self.assertIn("根因就是 X", user)
        self.assertIn("unsupported_absolute", user)
        self.assertIn("本轮没有工具结果", user)


if __name__ == "__main__":
    unittest.main(verbosity=2)
