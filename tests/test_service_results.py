# -*- coding: utf-8 -*-
"""结果资产：唯一键去重、状态机、force、恢复孤儿、对外形状。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import store
from learnsys.services import results

KEY = dict(kind="cet6_analyze", target_type="item", target_id="p1|A|C1",
           scope="item", context_hash="abc", prompt_version="v1")


class ServiceResultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.conn = store.connect(pathlib.Path(self.tmp.name) / "learning.db")
        self.addCleanup(self.conn.close)

    def test_create_dedupes_by_unique_key(self):
        first, created = results.create(
            self.conn, model="m", input_json="{}", **KEY)
        second, created_again = results.create(
            self.conn, model="m", input_json="{}", **KEY)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, second)

    def test_find_done_only_returns_done(self):
        rid, _ = results.create(self.conn, model="m", input_json="{}", **KEY)
        self.assertIsNone(results.find_done(self.conn, **KEY))
        results.update(self.conn, rid, status="done", content_json='{"summary":"ok"}')
        found = results.find_done(self.conn, **KEY)
        self.assertIsNotNone(found)
        self.assertEqual(found["status"], "done")

    def test_force_supersedes_old_row(self):
        rid, _ = results.create(self.conn, model="m", input_json="{}", **KEY)
        results.update(self.conn, rid, status="done", content_json="{}")
        changed = results.mark_superseded(self.conn, **KEY)
        self.assertEqual(changed, 1)
        self.assertEqual(results.get(self.conn, rid)["status"], "superseded")

    def test_latest_and_recover_orphans(self):
        rid, _ = results.create(self.conn, model="m", input_json="{}", **KEY)
        latest = results.latest(self.conn, kind="cet6_analyze",
                                target_type="item", target_id="p1|A|C1")
        self.assertEqual(latest["id"], rid)
        self.assertEqual(results.recover_orphans(self.conn), 1)
        recovered = results.get(self.conn, rid)
        self.assertEqual(recovered["status"], "error")
        self.assertIn("后台重启", recovered["error"])

    def test_to_public_hides_input_and_parses_content(self):
        rid, _ = results.create(self.conn, model="m", input_json='{"secret":1}', **KEY)
        results.update(self.conn, rid, status="done",
                       content_json='{"summary":"结果"}')
        public = results.to_public(results.get(self.conn, rid))
        self.assertNotIn("input_json", public)
        self.assertEqual(public["content"]["summary"], "结果")
        self.assertEqual(public["cache_hit"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
