# -*- coding: utf-8 -*-
"""一句一译：题库不泄漏参考、同步审核、尝试落库、必改进错误卡。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.server.app import create_app
from learnsys.services import train_review, train_sentences as service
from learnsys.services import train_submissions as submissions
from learnsys.train import content

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}
TEXT = "As city people grow, housing and traffic face new pressure."
PAYLOAD = {
    "conclusion": "有偏差",
    "info_points": {"total": 2, "covered": 1, "missing": ["城市人口增长"]},
    "must_fix": [
        {"quote": "city people", "fix": "the urban population", "why": "用词不准"},
        {"quote": "not in the text", "fix": "x", "why": "编造"},
    ],
    "suggestions": [
        {"quote": "face new pressure", "fix": "are under new pressure",
         "why": "更自然"},
    ],
    "variants": ["As the urban population grows, housing and transport face new pressure."],
    "minimal_fix": "As the urban population grows, housing and traffic face new pressure.",
    "idiomatic": "With a growing urban population, housing and transport are under increasing pressure.",
}


def fake_run(request, cfg=None, abort=None, **_kwargs):
    yield AgentEvent("done", data={
        "text": json.dumps(PAYLOAD, ensure_ascii=False),
        "usage": {"input_tokens": 10, "output_tokens": 5}})


class SentenceServiceTest(unittest.TestCase):
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
        self.patch_run = mock.patch.object(train_review.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)

    def test_list_never_exposes_reference(self):
        conn = store.connect()
        try:
            data = service.list_sentences(conn, skill="语序调整", limit=20)
            self.assertGreaterEqual(data["count"], 6)
            self.assertTrue(all(item["skill"] == "语序调整" for item in data["items"]))
            for item in data["items"]:
                self.assertNotIn("reference", item)
                self.assertNotIn("variants", item)
                self.assertTrue(item["zh"])
            self.assertIn("语序调整", data["skills"])
        finally:
            conn.close()

    def test_review_persists_attempt_and_only_must_fix_cards(self):
        conn = store.connect()
        try:
            data = service.review_sentence(conn, "x001", TEXT)
            review = data["review"]
            self.assertEqual(review["reference"], content.sentence("x001")["reference"])
            self.assertEqual(len(review["must_fix"]), 1)
            self.assertEqual(len(review["suggestions"]), 1)
            self.assertEqual(review["errors_dropped"], 1)
            self.assertEqual(len(review["cards"]), 1)
            self.assertEqual(data["cards_added"], 1)

            attempted = store.sentence_attempted(conn)
            self.assertIn("x001", attempted)
            rows = store.list_submissions(conn, kind="translation", mode="sentence")
            self.assertEqual(rows["count"], 1)
            self.assertEqual(rows["items"][0]["status"], "reviewed")
            self.assertIsNone(rows["items"][0]["band"])
            wrong = store.wrong_items(conn, source="translation")
            self.assertEqual(len(wrong), 1)
            self.assertIn("city people", wrong[0]["question"])

            history = submissions.history(conn, "translation")
            self.assertEqual(history["count"], 0, "单句尝试不进整篇历史")

            again = service.review_sentence(conn, "x001", TEXT)
            self.assertEqual(again["cards_added"], 0, "同一错误不重复收卡")
            self.assertEqual(len(store.wrong_items(conn, source="translation")), 1)
        finally:
            conn.close()

    def test_translation_prompt_and_detail_split(self):
        conn = store.connect()
        try:
            prompt = submissions.prompt_detail("translation", "t01")
            self.assertIn("source_zh", prompt)
            for key in ("segments", "reference", "terms", "info_points"):
                self.assertNotIn(key, prompt)
            terms = submissions.list_terms()
            self.assertGreater(terms["count"], 100)
            self.assertTrue(all(row["zh"] and row["en"] for row in terms["items"]))
            packs = {row["pack_id"] for row in terms["items"]}
            self.assertIn("t01", packs)
        finally:
            conn.close()

    def test_unknown_sentence_and_empty_text(self):
        conn = store.connect()
        try:
            with self.assertRaises(LookupError):
                service.review_sentence(conn, "nope", "Something")
            with self.assertRaises(ValueError):
                service.review_sentence(conn, "x001", "   ")
        finally:
            conn.close()


class SentenceRoutesTest(unittest.TestCase):
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
        self.patch_run = mock.patch.object(train_review.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_sentence_routes(self):
        self.assertEqual(
            self.client.get("/api/cet6/train/sentences").status_code, 403)
        data = self.client.get("/api/cet6/train/sentences",
                               params={"limit": 5}, headers=AUTH).json()
        self.assertEqual(len(data["items"]), 5)
        self.assertNotIn("reference", data["items"][0])

        reviewed = self.client.post(
            "/api/cet6/train/sentences/x001/review",
            json={"text": TEXT, "pasted_chars": 0, "left_seconds": 0},
            headers=AUTH)
        self.assertEqual(reviewed.status_code, 200)
        body = reviewed.json()
        self.assertTrue(body["review"]["reference"])
        self.assertEqual(len(body["review"]["must_fix"]), 1)
        self.assertGreaterEqual(body["attempt_id"], 1)
        self.assertEqual(body["cards_added"], 1)

        wrong = self.client.get("/api/wrongbook", params={"source": "translation"},
                                headers=AUTH).json()
        self.assertEqual(len(wrong["items"]), 1)

        listed = self.client.get("/api/cet6/train/sentences",
                                 params={"limit": 200}, headers=AUTH).json()
        first = next(row for row in listed["items"] if row["id"] == "x001")
        self.assertTrue(first["attempted"])

        plan = self.client.get("/api/cet6/train/plan", headers=AUTH).json()
        self.assertEqual(plan["today"]["sentence"], 1)
        self.assertEqual(plan["streak"], 1)
        stats = self.client.get("/api/cet6/train/stats", headers=AUTH).json()
        self.assertEqual(stats["totals"]["sentences"], 1)
        self.assertEqual(stats["by_kind"]["translation"]["sentences"], 1)
        self.assertEqual(stats["error_types"][0]["type"], "用词")
        overview = self.client.get("/api/overview", headers=AUTH).json()
        self.assertEqual(overview["today"]["train_sentence"], 1)
        self.assertEqual(overview["today"]["xp"], 5)

    def test_terms_and_prompt_privacy(self):
        terms = self.client.get("/api/cet6/train/terms", headers=AUTH).json()
        self.assertGreater(terms["count"], 100)
        one = self.client.get("/api/cet6/train/terms",
                              params={"pack_id": "t01"}, headers=AUTH).json()
        self.assertTrue(one["count"] >= 8)
        prompt = self.client.get(
            "/api/cet6/train/prompts/t01",
            params={"kind": "translation"}, headers=AUTH).json()
        self.assertNotIn("segments", prompt)
        self.assertNotIn("reference", prompt)
        self.assertNotIn("terms", prompt)


if __name__ == "__main__":
    unittest.main()
