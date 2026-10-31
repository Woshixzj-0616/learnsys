# -*- coding: utf-8 -*-
"""六级意群长句接口：令牌、队列、提交、统计。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config, store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}
PAPER = "卷一"
SENTENCE = ("When I teach in the classroom, we often talk about success "
            "and what leads to success.")


def _write_paper(root: pathlib.Path) -> None:
    paper = root / "试卷" / PAPER
    base = paper / "Section-A-长对话" / "01-Conversation-1"
    (base / "句子").mkdir(parents=True)
    (base / "句子" / "01.mp3").write_bytes(b"")
    (base / "正文.mp3").write_bytes(b"")
    (base / "题目.mp3").write_bytes(b"")
    words = []
    moment = 10.0
    for index, token in enumerate(SENTENCE.split()):
        duration = 0.35 if len(token) > 4 else 0.25
        words.append({"start": round(moment, 2), "end": round(moment + duration, 2),
                      "word": token})
        moment += duration + (0.5 if index == 5 else 0.03)
    data = {
        "paper_id": "卷一_100", "title": PAPER,
        "sections": [{
            "letter": "A", "name": "Section A 长对话",
            "items": [{
                "index": 1, "title": "Conversation 1",
                "paths": {
                    "content": "Section-A-长对话/01-Conversation-1/正文.mp3",
                    "questions": "Section-A-长对话/01-Conversation-1/题目.mp3",
                },
                "sentences": [{"i": 1, "start": 10.0, "end": round(moment, 2),
                               "en": SENTENCE}],
            }],
        }],
    }
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")
    (paper / "transcript.json").write_text(json.dumps({
        "segments": [{"start": 10.0, "end": round(moment, 2),
                      "text": SENTENCE, "words": words}],
    }, ensure_ascii=False), encoding="utf-8")


class Cet6ChunkRoutesTest(unittest.TestCase):
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
            rows=[{"sentence": 1, "en": SENTENCE}], done=[])
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
            self.client.get("/api/cet6/chunk/queue").status_code, 403)

    def test_queue_returns_long_sentence_without_chunks(self):
        response = self.client.get("/api/cet6/chunk/queue", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertEqual(item["sentence"], 1)
        self.assertGreaterEqual(item["word_count"], 12)
        self.assertNotIn("chunks", item)

    def test_attempt_and_stats(self):
        response = self.client.post("/api/cet6/chunk/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "sentence": 1,
            "answer": SENTENCE, "duration_s": 30})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["score"], 1.0)
        self.assertGreaterEqual(data["chunk_count"], 2)
        self.assertTrue(data["chunks"][0]["text"])

        stats = self.client.get(
            "/api/cet6/chunk/stats", headers=AUTH).json()
        self.assertEqual(stats["total_attempts"], 1)
        self.assertEqual(stats["sentences"], 1)

    def test_attempt_unknown_sentence_returns_404(self):
        response = self.client.post("/api/cet6/chunk/attempt", headers=AUTH, json={
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "sentence": 99, "answer": "x"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
