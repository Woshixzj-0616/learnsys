# -*- coding: utf-8 -*-
"""快捷栏公式兜底：LaTeX → Unicode，代码与货币不误伤。"""
from __future__ import annotations

import unittest

from learnsys.ask.quickbar import math_text


class MathTextTest(unittest.TestCase):
    def test_common_formulas(self):
        self.assertEqual(math_text.render(r"$H(K)=3K \bmod 11$"),
                         "H(K)=3K mod 11")
        self.assertEqual(math_text.render(r"$\frac{10}{8}=1.25$"), "10/8=1.25")
        self.assertEqual(math_text.render(r"$\lceil \log_2(23) \rceil = 5$"),
                         "⌈ log₂(23) ⌉ = 5")
        self.assertEqual(math_text.render(r"$x^2 + y_1$"), "x² + y₁")
        self.assertEqual(math_text.render(r"$\nabla f$"), "∇ f")
        self.assertEqual(math_text.render(r"\(\alpha \le \beta\)"), "α ≤ β")

    def test_display_and_nested(self):
        self.assertEqual(math_text.render(r"$$\frac{a+b}{c}$$"), "(a+b)/c")
        self.assertEqual(math_text.render(r"$\frac{\frac{a}{b}}{c}$"),
                         "(a/b)/c")
        self.assertEqual(math_text.render(r"$\sqrt[3]{x}$"), "∛(x)")
        self.assertEqual(math_text.render(r"$\text{速度}$"), "速度")

    def test_matrix_degrades_without_backslashes(self):
        text = "$\\begin{matrix}a&b\\\\c&d\\end{matrix}$"
        out = math_text.render(text)
        self.assertEqual(out, "a, b；c, d")
        self.assertNotIn("\\", out)

    def test_code_is_untouched(self):
        text = "```cpp\nfor (int i=0;i<n;i++) cout << \"$x$\";\n```"
        self.assertEqual(math_text.render(text), text)
        self.assertEqual(math_text.render("行内 `$x$` 不动"), "行内 `$x$` 不动")
        unclosed = "```python\nprint('$x$')"
        self.assertEqual(math_text.render(unclosed), unclosed)

    def test_currency_is_not_math(self):
        for text in ("价格 $5 和 $10 元", "$5 and $10", "只要 $5"):
            self.assertEqual(math_text.render(text), text)

    def test_unclosed_delimiter_is_left_alone(self):
        self.assertEqual(math_text.render("还没闭合 $x^2"), "还没闭合 $x^2")

    def test_unknown_command_keeps_readable_name(self):
        out = math_text.render(r"$\foo bar$")
        self.assertIn("foo", out)
        self.assertNotIn("\\", out)


if __name__ == "__main__":
    unittest.main()
