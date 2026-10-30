# -*- coding: utf-8 -*-
"""P30.3 创作库 store：风格预设、作品、归档与引用清零。"""
from __future__ import annotations

import unittest

from learnsys import store


class ArtStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_preset_upsert_by_name(self):
        first = store.upsert_art_preset(
            self.conn, name="霓虹赛博", prompt="霓虹灯、雨夜、赛博朋克",
            negative="模糊", note="常用")
        second = store.upsert_art_preset(
            self.conn, name="霓虹赛博", prompt="霓虹灯、雨夜、赛博朋克、电影感")
        self.assertEqual(first["id"], second["id"])
        self.assertIn("电影感", second["prompt"])
        self.assertEqual(len(store.list_art_presets(self.conn)), 1)

    def test_empty_preset_name_rejected(self):
        with self.assertRaises(ValueError):
            store.upsert_art_preset(self.conn, name="  ")

    def test_work_crud_and_status(self):
        preset = store.upsert_art_preset(self.conn, name="水彩")
        work = store.add_art_work(
            self.conn, title="山谷", prompt="晨雾中的山谷，水彩",
            preset_id=preset["id"], model="豆包", note="第一版")
        self.assertEqual(work["status"], "active")
        self.assertEqual(work["preset_id"], preset["id"])
        self.assertEqual(store.list_art_works(self.conn), [work])
        archived = store.set_art_work_status(self.conn, work["id"], "archived")
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(store.list_art_works(self.conn), [])
        self.assertEqual(
            [item["id"] for item in store.list_art_works(self.conn,
                                                         status="archived")],
            [work["id"]])
        restored = store.set_art_work_status(self.conn, work["id"], "active")
        self.assertEqual(restored["status"], "active")

    def test_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            store.add_art_work(self.conn, title=" ")

    def test_update_whitelist(self):
        work = store.add_art_work(self.conn, title="旧标题")
        updated = store.update_art_work(
            self.conn, work["id"], title="新标题", prompt="新提示词")
        self.assertEqual(updated["title"], "新标题")
        self.assertEqual(updated["prompt"], "新提示词")
        with self.assertRaises(ValueError):
            store.update_art_work(self.conn, work["id"], title="")

    def test_delete_preset_clears_work_reference(self):
        preset = store.upsert_art_preset(self.conn, name="纸感")
        work = store.add_art_work(self.conn, title="街角",
                                  preset_id=preset["id"])
        self.assertIsNotNone(store.delete_art_preset(self.conn, preset["id"]))
        self.assertEqual(store.get_art_work(self.conn, work["id"])["preset_id"], 0)
        self.assertEqual(store.list_art_presets(self.conn), [])

    def test_delete_work(self):
        work = store.add_art_work(self.conn, title="临时")
        self.assertIsNotNone(store.delete_art_work(self.conn, work["id"]))
        self.assertIsNone(store.get_art_work(self.conn, work["id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
