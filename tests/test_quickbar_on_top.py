# -*- coding: utf-8 -*-
"""置顶状态的来源判定（2026-10-28）。

锁一件事：旧版 `界面设置.json` 里残留的 `always_on_top: false` 不能永久压住
config 里的默认值；只有用户点过开关（`always_on_top_set: true`）才认文件里的值。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.ask.quickbar.common import resolve_on_top  # noqa: E402


class ResolveOnTopTest(unittest.TestCase):
    def test_legacy_false_is_ignored(self) -> None:
        """旧文件只有 always_on_top=false、没有 set 标记 ⇒ 用默认值 True。"""
        self.assertTrue(resolve_on_top({"always_on_top": False}, True))

    def test_legacy_string_false_is_ignored(self) -> None:
        """手改成的字符串 "false" 同样按历史残留处理。"""
        self.assertTrue(resolve_on_top({"always_on_top": "false"}, True))

    def test_missing_key_uses_default(self) -> None:
        self.assertTrue(resolve_on_top({}, True))
        self.assertFalse(resolve_on_top({}, False))

    def test_user_choice_false_wins(self) -> None:
        state = {"always_on_top": False, "always_on_top_set": True}
        self.assertFalse(resolve_on_top(state, True))

    def test_user_choice_true_wins(self) -> None:
        state = {"always_on_top": True, "always_on_top_set": True}
        self.assertTrue(resolve_on_top(state, False))

    def test_user_choice_string_values(self) -> None:
        """设置文件可能是手写的字符串，仍按 _as_bool 的规则读。"""
        self.assertFalse(resolve_on_top(
            {"always_on_top": "false", "always_on_top_set": "true"}, True))
        self.assertTrue(resolve_on_top(
            {"always_on_top": "true", "always_on_top_set": "yes"}, False))

    def test_false_set_marker_is_not_a_user_choice(self) -> None:
        """set 标记本身写成 false ⇒ 没选过，回落到默认。"""
        state = {"always_on_top": True, "always_on_top_set": "false"}
        self.assertFalse(resolve_on_top(state, False))


if __name__ == "__main__":
    unittest.main()
