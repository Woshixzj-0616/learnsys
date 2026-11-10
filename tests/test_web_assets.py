# -*- coding: utf-8 -*-
"""前端资源登记一致性：index.html 引用的样式必须在 SW 预缓存里。

手工三处登记（页面、index.html、sw.js）容易漂移；这里只查最容易漏的一处：
index.html 的 CSS 与 sw.js 的 CORE 清单必须一一对应（顺序不限）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
SW = (ROOT / "web/sw.js").read_text(encoding="utf-8")
ENGLISH = (ROOT / "web/js/pages/english/index.js").read_text(encoding="utf-8")
CET6_DIR = ROOT / "web/js/pages/cet6"


class WebAssetTest(unittest.TestCase):
    def test_every_linked_css_is_precached(self):
        linked = set(re.findall(r'href="(/web/css/[^"]+\.css)"', INDEX))
        cached = set(re.findall(r'"(/web/css/[^"]+\.css)"', SW))
        self.assertEqual(sorted(linked - cached), [],
                         "index.html 引用了但 SW 没预缓存的样式")
        self.assertEqual(sorted(cached - linked), [],
                         "SW 预缓存了但 index.html 没引用的样式")

    def test_every_css_file_is_linked(self):
        linked = set(re.findall(r'href="/web/css/([^"]+\.css)"', INDEX))
        on_disk = {path.name for path in (ROOT / "web/css").glob("*.css")}
        self.assertEqual(sorted(on_disk - linked), [],
                         "web/css 下有样式没被 index.html 引用")

    def test_english_shell_mounts_the_ai_drawer(self):
        self.assertIn("mount as mountAI", ENGLISH)
        self.assertIn("mountAI(root)", ENGLISH)
        self.assertIn("setEnabled(tab !== \"listening\")", ENGLISH)
        self.assertIn("setPage", ENGLISH)

    def test_retired_practice_modules_stay_removed(self):
        for name in ("practice.js", "drill.js", "exam.js", "chunk.js"):
            self.assertFalse((CET6_DIR / name).exists(),
                             f"已退休的 {name} 又被加回来了")
        for path in (ROOT / "web/js").rglob("*.js"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in ("practice.js", "drill.js", "exam.js", "chunk.js"):
                self.assertNotIn(f'"./{name}"', text,
                                 f"{path.relative_to(ROOT)} 又引用了 {name}")
                self.assertNotIn(f'"../cet6/{name}"', text,
                                 f"{path.relative_to(ROOT)} 又引用了 {name}")


if __name__ == "__main__":
    unittest.main()
