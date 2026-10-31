# -*- coding: utf-8 -*-
"""六级真题自评接口：令牌、队列、提交校验、统计。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import urllib.parse
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}
PAPER = "卷一"


def _write_paper(root: pathlib.Path) -> None:
    paper = root / "试卷" / PAPER
    base = paper / "Section-A-长对话" / "01-Conversation-1"
    (base / "问题").mkdir(parents=True)
    (base / "正文.mp3").write_bytes(b"")
    (base / "题目.mp3").write_bytes(b"")
    for index in (1, 2):
        (base / "问题" / f"{index:02d}.mp3").write_bytes(b"")
    data = {
        "paper_id": "卷一_100",
        "title": PAPER,
        "sections": [{
            "letter": "A", "name": "Section A 长对话",
            "items": [{
                "index": 1, "title": "Conversation 1",
                "paths": {
                    "content": "Section-A-长对话/01-Conversation-1/正文.mp3",
                    "questions": "Section-A-长对话/01-Conversation-1/题目.mp3",
                },
                "question_items": [
                    {"i": 1, "number": 1, "en": "What do we learn about the man?"},
                    {"i": 2, "number": 2, "en": "Why does he suggest they stop?"},
                ],
            }],
        }],
    }
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")


class Cet6ExamRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        _write_paper(self.root)
        self.db_path = self.root / "learning.db"
        conn = store.connect(self.db_path)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title=PAPER,
            section="Section A 长对话", item="Conversation 1",
            rows=[{"sentence": 1, "en": "Hello there."},
                  {"sentence": 2, "en": "Nice to meet you."}], done=[])
        conn.close()

        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.cet6_patch = mock.patch.object(
            config, "cet6_dir", return_value=self.root)
        self.cet6_patch.start()
        self.addCleanup(self.cet6_patch.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_queue_requires_token(self):
        self.assertEqual(
            self.client.get("/api/cet6/exam/queue").status_code, 403)

    def test_queue_returns_questions_without_transcript(self):
        response = self.client.get("/api/cet6/exam/queue", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertEqual(item["paper_title"], PAPER)
        self.assertEqual(len(item["questions"]), 2)
        self.assertTrue(
            urllib.parse.unquote(item["audio_url"]).endswith("/正文.mp3"))
        self.assertNotIn("transcript", item)

    def test_attempt_and_stats(self):
        response = self.client.post("/api/cet6/exam/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [1], "duration_s": 40})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["question_count"], 2)
        self.assertEqual(data["correct_count"], 1)
        self.assertEqual(data["self_accuracy"], 0.5)
        self.assertEqual(len(data["transcript"]), 2)

        stats = self.client.get("/api/cet6/exam/stats", headers=AUTH).json()
        self.assertEqual(stats["total_attempts"], 1)
        self.assertEqual(stats["items"], 1)
        self.assertEqual(stats["by_section"]["A"]["self_accuracy"], 0.5)

    def test_attempt_rejects_unknown_question_number(self):
        response = self.client.post("/api/cet6/exam/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [99]})
        self.assertEqual(response.status_code, 422)

    def test_attempt_unknown_item_returns_404(self):
        response = self.client.post("/api/cet6/exam/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 9", "wrong": []})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
