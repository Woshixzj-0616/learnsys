# -*- coding: utf-8 -*-
"""产品名与图标路径：改名后最容易漂移的几处，一次锁死。"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys import config, product  # noqa: E402
from learnsys.ask import workbench  # noqa: E402
from learnsys.modules import web_dir  # noqa: E402


class ProductNameTest(unittest.TestCase):
    def test_product_name_once(self):
        self.assertEqual(product.PRODUCT_NAME, "学习工作台")
        self.assertEqual(product.QNA_NAME, "问一问")

    def test_window_mark_matches_web_title(self):
        """focus_window 靠标题后缀找窗口 —— Python 和 JS 必须同一个串。"""
        self.assertEqual(workbench.WINDOW_MARK, f"· {product.PRODUCT_NAME}")
        shell = (web_dir() / "js" / "shell.js").read_text(encoding="utf-8")
        self.assertIn(f'const PRODUCT_NAME = "{product.PRODUCT_NAME}"', shell)
        self.assertIn("`${module.name} · ${PRODUCT_NAME}`", shell)

    def test_index_title_and_brand(self):
        index = (web_dir() / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"<title>今日 · {product.PRODUCT_NAME}</title>", index)
        self.assertIn(f'<span class="brand-name">{product.PRODUCT_NAME}</span>', index)
        self.assertIn("/favicon.ico?v=2", index)

    def test_manifest_name(self):
        data = json.loads((web_dir() / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], product.PRODUCT_NAME)
        self.assertEqual(data["short_name"], product.PRODUCT_NAME)
        self.assertEqual(data["id"], "/")            # 不改 PWA 身份
        self.assertEqual(data["start_url"], "/")

    def test_icon_path_and_assets(self):
        self.assertEqual(config.ICON_PATH.name, f"{product.PRODUCT_NAME}.ico")
        self.assertTrue(config.ICON_PATH.exists(), config.ICON_PATH)
        for name in ("icon-192.png", "icon-512.png",
                     "icon-maskable-512.png", "apple-touch-icon.png"):
            self.assertTrue((web_dir() / "icons" / name).exists(), name)

    def test_qna_feature_name_kept(self):
        ask = json.loads((pathlib.Path(config.ROOT) / "learnsys" / "plugins" / "ask"
                          / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(ask["name"], product.QNA_NAME)

    def test_spec_uses_new_names(self):
        spec = (pathlib.Path(config.ROOT) / f"{product.PRODUCT_NAME}.spec").read_text(
            encoding="utf-8")
        self.assertIn("name='学习工作台'", spec)
        self.assertIn("学习工作台.py", spec)
        self.assertIn("学习工作台.ico", spec)
        self.assertNotIn("问一问.exe", spec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
