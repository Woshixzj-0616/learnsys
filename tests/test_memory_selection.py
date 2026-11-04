"""记忆选择：硬规矩必带、作用域优先、预算、冲突压制、使用计数。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.agent import memory


class TestMemorySelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.conn.close)

    def _add(self, content, **kwargs):
        return store.add_memory(self.conn, content, **kwargs)[0]

    def test_pinned_rule_is_always_included(self):
        rule = self._add("回答一律用中文", kind="rule", confidence=0.9,
                         pinned=1)
        self._add("周末喜欢去图书馆", scope="global")
        result = memory.select_for_prompt(
            self.root, query="解释一下快速排序", scope_hints=())
        self.assertIn(rule, result["ids"])

    def test_scope_hint_beats_global(self):
        cet6 = self._add("听力先看题再听", scope="exam:cet6", confidence=0.8)
        for index in range(15):
            self._add(f"全局偏好编号{index}", scope="global", confidence=0.8)
        result = memory.select_for_prompt(
            self.root, query="六级听力怎么练", scope_hints=("exam:cet6",))
        self.assertIn(cet6, result["ids"])

    def test_unrelated_specific_scope_not_injected(self):
        course = self._add("这门课先看第三章", scope="course:离散数学")
        result = memory.select_for_prompt(
            self.root, query="今天天气怎么样", scope_hints=())
        self.assertNotIn(course, result["ids"])

    def test_budget_items_and_chars(self):
        for index in range(40):
            self._add("这是一条比较长的记忆内容" * 3 + str(index))
        result = memory.select_for_prompt(
            self.root, query="复习", limit=12, max_chars=1600)
        self.assertLessEqual(len(result["ids"]), 12)
        self.assertLessEqual(result["chars"], 1600)

    def test_mark_used_increments(self):
        memory_id = self._add("示例代码用 C++")
        memory.select_for_prompt(self.root, query="示例代码")
        row = store.get_memory(self.conn, memory_id)
        self.assertGreaterEqual(row["use_count"], 1)

    def test_profile_only_identity_goal_constraint(self):
        self._add("网络工程大二", kind="identity")
        self._add("十二月过六级", kind="goal")
        self._add("示例代码用 C++", kind="preference")
        text = memory.render_profile_for_prompt(self.root)
        self.assertIn("网络工程大二", text)
        self.assertIn("十二月过六级", text)
        self.assertNotIn("示例代码用 C++", text)


if __name__ == "__main__":
    unittest.main()
