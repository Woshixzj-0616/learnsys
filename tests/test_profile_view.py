"""画像视图：自动生成标记、来源、过期检测、手改会被覆盖。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.services import profile_view


class TestProfileView(unittest.TestCase):
    def test_compile_stale_and_regenerate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            conn = store.connect(root / "learning.db")
            try:
                store.add_memory(conn, "网络工程大二", kind="identity",
                                 confidence=0.95)
                store.add_memory(conn, "十二月过六级", kind="goal",
                                 confidence=0.9)
                result = profile_view.compile_profile(root)
                self.assertEqual(result["facts"], 2)
                text = profile_view.read_profile(root)
                self.assertIn("AUTO-GENERATED", text)
                self.assertIn("网络工程大二", text)
                self.assertIn("十二月过六级", text)
                self.assertFalse(profile_view.profile_is_stale(conn, root))

                store.add_memory(conn, "每周至少跑三次步", kind="goal")
                self.assertTrue(profile_view.profile_is_stale(conn, root))

                text_path = root / "记忆档案" / "画像.md"
                text_path.write_text("手改内容", encoding="utf-8")
                profile_view.compile_profile(root)
                self.assertNotIn("手改内容", profile_view.read_profile(root))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
