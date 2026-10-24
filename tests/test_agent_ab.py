"""P16.4 评测工具的确定性部分：评分口径与对照组提示词/工具集。"""
from __future__ import annotations

import unittest

from tools import agent_ab
from learnsys.agent import prompts, tools


class ScoreTest(unittest.TestCase):
    def test_groups_and_forbidden(self):
        task = {"groups": [r"后进先出|LIFO", r"先进先出|FIFO"],
                "forbid": [r"栈是先进先出"]}
        self.assertEqual(agent_ab._score(task, "", "栈后进先出，队列先进先出",
                                         True, set(), set()), 1.0)
        self.assertEqual(agent_ab._score(task, "", "栈是先进先出",
                                         True, set(), set()), 0.0)

    def test_require_tool_missing_is_zero(self):
        task = {"groups": [r"(^|\D)6(\D|$)"], "require_tool": "run_code"}
        self.assertEqual(agent_ab._score(task, "6", "6", True, set(), set()), 0.0)
        self.assertEqual(agent_ab._score(task, "6", "6", True,
                                         {"run_code"}, set()), 1.0)
        self.assertEqual(agent_ab._score(task, "6", "6", True,
                                         {"run_code"}, {"run_code"}), 0.0)

    def test_side_effect_is_binary(self):
        task = {"groups": [r"已保存"], "side_effect": "material_note"}
        self.assertEqual(agent_ab._score(task, "已保存", "已保存", True,
                                         set(), set()), 1.0)
        self.assertEqual(agent_ab._score(task, "已保存", "已保存", False,
                                         set(), set()), 0.0)


class ControlModeTest(unittest.TestCase):
    def test_control_hides_new_tools_and_prompt_rules(self):
        with agent_ab._control_mode(True):
            names = {schema["name"] for schema in tools.schemas_for("explain")}
            self.assertNotIn("make_plan", names)
            self.assertNotIn("recent_wrong_items", names)
            self.assertNotIn("run_code", names)
            self.assertNotIn("save_material_note", names)
            system = prompts.build_system("explain")
            self.assertNotIn("make_plan", system)
            self.assertNotIn("run_code", system)
            self.assertIn("长期记忆纪律", system)
            # 对照组必须同时回到旧的长度口径与旧示例，否则 A/B 测不出差异
            self.assertIn("1200–1800", system)
            self.assertNotIn("按问题复杂度", system)
            self.assertNotIn("只学取舍", system)
        self.assertIn("计划纪律", prompts.BASE_SYSTEM)


if __name__ == "__main__":
    unittest.main()
