# -*- coding: utf-8 -*-
"""P30.3 豆包文本导入：标签解析、无标签兜底、风格自动建档。"""
from __future__ import annotations

import unittest

from learnsys import store
from learnsys.services.life import art


class ArtImportParseTest(unittest.TestCase):
    def test_labeled_block(self):
        text = ("标题：霓虹城市\n"
                "提示词：赛博朋克街道，霓虹灯，雨夜\n"
                "风格：霓虹赛博\n"
                "模型：豆包\n"
                "备注：第一次尝试")
        blocks = art.parse_import(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["title"], "霓虹城市")
        self.assertIn("赛博朋克街道", blocks[0]["prompt"])
        self.assertEqual(blocks[0]["style"], "霓虹赛博")
        self.assertEqual(blocks[0]["model"], "豆包")
        self.assertEqual(blocks[0]["note"], "第一次尝试")

    def test_two_blocks_by_blank_line(self):
        text = ("标题：第一张\n提示词：山谷\n\n"
                "标题：第二张\n提示词：海边")
        blocks = art.parse_import(text)
        self.assertEqual([item["title"] for item in blocks], ["第一张", "第二张"])

    def test_unlabeled_block_uses_first_line_as_title(self):
        text = "山顶的日出\n金色的光穿过云层，远处有薄雾"
        blocks = art.parse_import(text)
        self.assertEqual(blocks[0]["title"], "山顶的日出")
        self.assertIn("金色的光", blocks[0]["prompt"])

    def test_block_without_title_gets_placeholder(self):
        blocks = art.parse_import("提示词：一只猫")
        self.assertEqual(blocks[0]["title"], "未命名作品")
        self.assertEqual(blocks[0]["prompt"], "一只猫")

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            art.parse_import("   \n  ")

    def test_caps_at_twenty_blocks(self):
        text = "\n\n".join(f"标题：作品{i}\n提示词：p{i}" for i in range(25))
        self.assertEqual(len(art.parse_import(text)), 20)


class ArtImportStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_import_creates_works_and_style(self):
        text = ("标题：霓虹城市\n提示词：赛博朋克街道\n风格：霓虹赛博\n模型：豆包\n\n"
                "标题：海边\n提示词：蓝色海面\n风格：霓虹赛博")
        items = art.import_works(self.conn, text)
        self.assertEqual(len(items), 2)
        presets = store.list_art_presets(self.conn)
        self.assertEqual([item["name"] for item in presets], ["霓虹赛博"])
        self.assertEqual(items[0]["preset_id"], presets[0]["id"])
        self.assertEqual(items[1]["preset_id"], presets[0]["id"])
        self.assertEqual(len(store.list_art_works(self.conn)), 2)

    def test_second_import_reuses_style(self):
        art.import_works(self.conn, "标题：一\n风格：水彩")
        art.import_works(self.conn, "标题：二\n风格：水彩")
        self.assertEqual(len(store.list_art_presets(self.conn)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
