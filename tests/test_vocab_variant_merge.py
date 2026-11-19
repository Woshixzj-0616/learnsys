# -*- coding: utf-8 -*-
"""生词变体合并工具：合并、归档、同词 accum 退出复习、幂等。"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

from learnsys import store

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "vocab_variant_merge.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("vocab_variant_merge_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VocabVariantMergeTest(unittest.TestCase):
    def setUp(self):
        self.tool = _load_tool()
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_collect_and_apply(self):
        # 先让 accum 卡存在，再加生词；这样能验证迁移工具会把它退出复习。
        self.conn.execute(
            "INSERT INTO cet6_accum_items (day, kind, ref_key, payload_json, status, "
            "created_at, updated_at) VALUES (?, 'translation', 'p1', ?, 'new', '', '')",
            ("2026-11-18",
             '{"zh":"商队","en":"Caravans"}'))
        accum_id = self.conn.execute(
            "SELECT id FROM cet6_accum_items").fetchone()[0]
        store.seed_review_states(self.conn, today="2026-11-19")
        self.assertIsNotNone(
            store.get_review_state(self.conn, "accum", accum_id))

        # 历史数据是直接落库的，不会经过 add_vocab 的 alias 合并；这里模拟旧库。
        def raw_vocab(word: str, meaning: str) -> None:
            self.conn.execute(
                "INSERT INTO vocab_items (word, normalized, meaning, status, "
                "source, created_at, updated_at) VALUES (?, ?, ?, 'active', "
                "'test', '2026-11-01 00:00:00', '2026-11-01 00:00:00')",
                (word, " ".join(word.lower().split()), meaning))

        raw_vocab("Caravans", "商队")
        raw_vocab("caravan", "商队")
        raw_vocab("advocate / uphold", "崇尚")
        raw_vocab("uphold", "崇尚")
        self.conn.commit()

        report = self.tool.collect(self.conn)
        self.assertEqual(len(report["plans"]), 2)
        applied = self.tool.apply(self.conn, report)
        self.assertEqual(applied["merged"], 2)
        self.assertEqual(applied["archived"], 2)
        self.assertEqual(applied["suppressed"], 1)

        active = [row["word"] for row in store.list_vocab(self.conn, limit=500)["items"]]
        self.assertIn("caravan", active)
        self.assertNotIn("Caravans", active)
        self.assertIn("uphold", active)
        self.assertNotIn("advocate / uphold", active)
        self.assertIsNone(
            store.get_review_state(self.conn, "accum", accum_id))

        again = self.tool.collect(self.conn)
        self.assertEqual(again["plans"], [])
        self.assertEqual(self.tool.apply(self.conn, again)["merged"], 0)


if __name__ == "__main__":
    unittest.main()
