# -*- coding: utf-8 -*-
"""代码调试判定：只有「长代码 + 调试意图」才算，普通问答不误伤。"""
from __future__ import annotations

import unittest

from learnsys.agent import debug_intent

CODE = """#include<iostream>
using namespace std;
int main() {
  int a;
  cin >> a;
  cout << a;
  return 0;
}
"""


class DebugIntentTest(unittest.TestCase):
    def test_code_plus_wa(self):
        self.assertTrue(debug_intent.detect(CODE + "这组输出没过，哪里错了？")["code_debug"])

    def test_code_plus_problem_long(self):
        code = "\n".join(["#include<iostream>"] + ["int x = 0;"] * 16)
        self.assertTrue(debug_intent.detect(code + "\n这段代码有什么问题")["code_debug"])

    def test_code_without_debug_words_is_false(self):
        self.assertFalse(debug_intent.detect(CODE + "帮我解释一下这段代码")["code_debug"])

    def test_prose_error_is_false(self):
        self.assertFalse(debug_intent.detect("这个错误是什么意思？为什么会报错？")["code_debug"])

    def test_short_snippet_is_false(self):
        self.assertFalse(debug_intent.detect("cout << 1; 为什么错？")["code_debug"])

    def test_signals_for_trace(self):
        data = debug_intent.detect(CODE + "报错了，超时")
        self.assertIn("#include", data["signals"])
        self.assertTrue(data["has_code"])


if __name__ == "__main__":
    unittest.main()
