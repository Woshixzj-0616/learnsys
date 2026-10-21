# -*- coding: utf-8 -*-
"""六级分析任务：缓存、去重、force、取消、超时、JSON 校验。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.services import analysis, results

RECORD = {
    "paper_id": "p1", "paper": "测试卷", "section": "Section A",
    "item": "Conversation 1", "scope": "item",
    "sentences": [{"sentence": 3, "en": "make out", "tags": ["连读"],
                   "note": "没听清", "loops": 4, "plays": 6}],
}
PAYLOAD = {"summary": "主要问题是连读", "patterns": [], "priority": [], "plan": []}


def fake_run(request, cfg=None, abort=None, **_kwargs):
    yield AgentEvent("done", data={
        "text": json.dumps(PAYLOAD, ensure_ascii=False),
        "usage": {"input_tokens": 12, "output_tokens": 4}})


class AnalysisJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.patch_run = mock.patch.object(analysis.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)

    def test_submit_poll_and_cache(self):
        first = analysis.submit(RECORD)
        self.assertEqual(first["status"], "pending")
        row = analysis.wait_result(first["id"], 5)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["tokens_in"], 12)
        self.assertIn("连读", row["content_json"])

        second = analysis.submit(RECORD)
        self.assertTrue(second["cached"])
        self.assertEqual(second["status"], "done")
        self.assertEqual(second["id"], first["id"])

    def test_force_creates_new_and_supersedes(self):
        first = analysis.submit(RECORD)
        analysis.wait_result(first["id"], 5)
        second = analysis.submit(RECORD, force=True)
        self.assertNotEqual(second["id"], first["id"])
        analysis.wait_result(second["id"], 5)
        conn = store.connect()
        try:
            old = results.get(conn, first["id"])
            new = results.get(conn, second["id"])
        finally:
            conn.close()
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["status"], "done")

    def test_cancel_pending(self):
        conn = store.connect()
        try:
            rid, _ = results.create(
                conn, kind=analysis.ANALYSIS_KIND, target_type="item",
                target_id="p1|A|C1", scope="item", context_hash="x",
                prompt_version=analysis.PROMPT_VERSION, model="m",
                input_json="{}")
        finally:
            conn.close()
        self.assertTrue(analysis.cancel(rid))
        conn = store.connect()
        try:
            self.assertEqual(results.get(conn, rid)["status"], "canceled")
        finally:
            conn.close()

    def test_timeout_marks_error(self):
        def slow_run(request, cfg=None, abort=None, **_kwargs):
            while not abort.is_set():
                time.sleep(0.01)
            yield AgentEvent("done", data={"text": ""})

        with mock.patch.object(analysis.agent, "run", slow_run), \
                mock.patch.object(analysis, "ANALYSIS_TIMEOUT", 0.2):
            submitted = analysis.submit(RECORD)
            row = analysis.wait_result(submitted["id"], 5)
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "分析超时")

    def test_validate_analysis_tolerates_bad_types(self):
        out = analysis.validate_analysis({
            "summary": 123, "patterns": ["x", {"name": "连读"}],
            "priority": [{"sentence": "3", "reason": "r"}, {"sentence": "bad"}],
            "plan": ["a", "", 3],
        })
        self.assertEqual(out["summary"], "123")
        self.assertEqual(out["patterns"][0]["name"], "连读")
        self.assertEqual(out["priority"][0]["sentence"], 3)
        self.assertEqual(out["plan"], ["a", "3"])

    def test_parse_repairs_unescaped_quotes_and_newlines(self):
        text = ('{"summary":"他说"连读"很难，\n第二行","patterns":[],'
                '"priority":[],"plan":[]}')
        obj = analysis.parse_json_text(text)
        self.assertIn('"连读"', obj["summary"])
        self.assertIn("\n第二行", obj["summary"])

    def test_normalize_sorts_and_dedupes(self):
        record = analysis.normalize_record({
            "sentences": [
                {"sentence": 5, "en": "b"},
                {"sentence": 2, "en": "a"},
                {"sentence": 5, "en": "dup"},
                {"sentence": "bad"},
            ]})
        self.assertEqual([row["sentence"] for row in record["sentences"]], [2, 5])
        self.assertEqual(record["sentences"][1]["en"], "b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
