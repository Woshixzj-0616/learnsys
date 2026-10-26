# -*- coding: utf-8 -*-
"""训练批改任务：三次取中位、缓存、force、单句同步、quote 过滤。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.services import results, train_review
from learnsys.train import content

WRITING_TEXT = ("I think part-time jobs are good because students can learn "
                "many things from them.")


def writing_payload(band: int) -> str:
    return json.dumps({
        "band": band, "band_reason": "结构清楚，但有搭配问题。",
        "off_topic": False,
        "dimensions": {"content": 3, "structure": 3, "language": 2,
                       "idiomatic": 1},
        "errors": [
            {"type": "搭配", "severity": "严重",
             "quote": "learn many things", "fix": "gain practical experience",
             "why": "搭配不自然"},
            {"type": "语法", "severity": "严重",
             "quote": "students should study harder", "fix": "study harder",
             "why": "原文没有这句"},
        ],
        "priorities": ["补具体例子", "检查冠词", "去掉 very"],
        "rewrite_task": "只改搭配和冠词。",
    }, ensure_ascii=False)


class TrainReviewJobsTest(unittest.TestCase):
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
        self.texts: list[str] = []
        self.calls = 0

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            text = self.texts[self.calls % len(self.texts)]
            self.calls += 1
            yield AgentEvent("done", data={
                "text": text,
                "usage": {"input_tokens": 12, "output_tokens": 4}})

        self.patch_run = mock.patch.object(train_review.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)

    def test_writing_median_quote_filter_and_cache(self):
        self.texts = [writing_payload(11), writing_payload(12),
                      writing_payload(13)]
        first = train_review.submit(
            {"kind": "writing", "prompt_id": "w01", "text": WRITING_TEXT})
        self.assertEqual(first["status"], "pending")
        row = train_review.wait_result(first["id"], 10)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "done")
        data = json.loads(row["content_json"])
        self.assertEqual(data["band"], 12)
        self.assertEqual(data["stability"]["spread"], 2)
        self.assertFalse(data["stability"]["stable"])
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors_dropped"], 1)
        self.assertEqual(len(data["cards"]), 1)
        self.assertEqual(data["samples_ok"], 3)
        self.assertEqual(row["tokens_in"], 36)
        self.assertEqual(row["tokens_out"], 12)
        self.assertEqual(self.calls, 3)

        second = train_review.submit(
            {"kind": "writing", "prompt_id": "w01", "text": WRITING_TEXT})
        self.assertTrue(second["cached"])
        self.assertEqual(second["id"], first["id"])

    def test_force_supersedes_old_result(self):
        self.texts = [writing_payload(12)]
        first = train_review.submit(
            {"kind": "writing", "prompt_id": "w01", "text": WRITING_TEXT})
        train_review.wait_result(first["id"], 10)
        second = train_review.submit(
            {"kind": "writing", "prompt_id": "w01", "text": WRITING_TEXT},
            force=True)
        self.assertNotEqual(second["id"], first["id"])
        train_review.wait_result(second["id"], 10)
        conn = store.connect()
        try:
            old = results.get(conn, first["id"])
            new = results.get(conn, second["id"])
        finally:
            conn.close()
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["status"], "done")

    def test_translation_missing_points_clamp_band(self):
        pack = content.pack("translation", "t01")
        self.texts = [json.dumps({
            "band": 12, "band_reason": "语言尚可，但漏译较多。",
            "info_points": {"missing": ["ip1", "ip2"]},
            "dimensions": {"coverage": 2, "accuracy": 3, "fluency": 3,
                           "terminology": 3},
            "errors": [
                {"type": "术语", "severity": "严重",
                 "quote": "Spring Festival", "fix": "the Spring Festival",
                 "why": "专有名词需要冠词"},
            ],
        }, ensure_ascii=False)]
        first = train_review.submit(
            {"kind": "translation", "prompt_id": "t01", "text": pack["reference"]})
        row = train_review.wait_result(first["id"], 10)
        self.assertEqual(row["status"], "done")
        data = json.loads(row["content_json"])
        self.assertEqual(data["band"], 8)
        self.assertEqual(data["info_points"]["missing"], ["ip1", "ip2"])
        self.assertEqual(len(data["term_cards"]), 1)

    def test_sentence_sync_uses_one_sample(self):
        self.texts = [json.dumps({
            "conclusion": "基本准确",
            "info_points": {"total": 1, "covered": 1, "missing": []},
            "must_fix": [
                {"quote": "most important", "fix": "the most important",
                 "why": "缺冠词"},
                {"quote": "not in the text", "fix": "x", "why": "编造"},
            ],
            "suggestions": [],
            "variants": ["The Spring Festival is China's most important festival."],
            "minimal_fix": "Spring Festival is the most important traditional festival in China.",
            "idiomatic": "The Spring Festival is China's foremost traditional festival.",
        }, ensure_ascii=False)]
        data = train_review.review_sync({
            "kind": "sentence", "prompt_id": "t01-s1",
            "text": "Spring Festival is the most important traditional festival in China.",
        })
        result = data["review"]
        self.assertEqual(result["conclusion"], "基本准确")
        self.assertEqual(len(result["must_fix"]), 1)
        self.assertEqual(result["errors_dropped"], 1)
        self.assertEqual(result["reference"], content.sentence("t01-s1")["reference"])
        self.assertEqual(self.calls, 1)

    def test_rejects_unknown_prompt_and_short_text(self):
        with self.assertRaises(ValueError):
            train_review.submit({"kind": "writing", "prompt_id": "nope",
                                 "text": "This is long enough to submit."})
        with self.assertRaises(ValueError):
            train_review.submit({"kind": "writing", "prompt_id": "w01",
                                 "text": "短"})
        with self.assertRaises(ValueError):
            train_review.submit({"kind": "reading", "prompt_id": "w01",
                                 "text": "This is long enough to submit."})


if __name__ == "__main__":
    unittest.main()
