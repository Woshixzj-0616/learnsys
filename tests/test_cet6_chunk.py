# -*- coding: utf-8 -*-
"""六级意群长句：切分、队列、提交、建卡、统计。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import urllib.parse
from unittest import mock

from learnsys import config, store
from learnsys.services import cet6_chunk, cet6_paper

PAPER = "卷一"
SENTENCE = ("When I teach in the classroom, we often talk about success "
            "and what leads to success.")
SHORT = "Hello there."


def _words(start: float, text: str) -> tuple[list[dict], float]:
    words = []
    moment = start
    for index, token in enumerate(text.split()):
        duration = 0.35 if len(token) > 4 else 0.25
        words.append({"start": round(moment, 2), "end": round(moment + duration, 2),
                      "word": token})
        moment += duration + (0.5 if index == 5 else 0.03)
    return words, moment


def _write_paper(root: pathlib.Path) -> None:
    paper = root / "试卷" / PAPER
    base = paper / "Section-A-长对话" / "01-Conversation-1"
    (base / "句子").mkdir(parents=True)
    for name in ("01.mp3", "02.mp3"):
        (base / "句子" / name).write_bytes(b"")
    (base / "正文.mp3").write_bytes(b"")
    (base / "题目.mp3").write_bytes(b"")
    long_words, long_end = _words(10.0, SENTENCE)
    short_words, short_end = _words(long_end + 1.0, SHORT)
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
                "sentences": [
                    {"i": 1, "start": 10.0, "end": round(long_end, 2),
                     "en": SENTENCE},
                    {"i": 2, "start": round(long_end + 1.0, 2),
                     "end": round(short_end, 2), "en": SHORT},
                ],
            }],
        }],
    }
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")
    transcript = {"segments": [{
        "start": 10.0, "end": round(short_end, 2), "text": SENTENCE + " " + SHORT,
        "words": long_words + short_words,
    }]}
    (paper / "transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False), encoding="utf-8")


class ChunkServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        _write_paper(self.root)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)
        self.cet6_patch = mock.patch.object(
            config, "cet6_dir", return_value=self.root)
        self.cet6_patch.start()
        self.addCleanup(self.cet6_patch.stop)
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title=PAPER,
            section="Section A 长对话", item="Conversation 1",
            rows=[{"sentence": 1, "en": SENTENCE, "note": "and 后面没跟上"},
                  {"sentence": 2, "en": SHORT}], done=[])

    def test_build_chunks_splits_meaning_groups(self):
        data = cet6_paper.sentence_words(
            PAPER, "Section A 长对话", "Conversation 1", 1)
        chunks = cet6_chunk.build_chunks(
            data["text"], data["words"], data["clip_start"], data["end"])
        self.assertGreaterEqual(len(chunks), 2)
        self.assertLessEqual(len(chunks), 5)
        self.assertTrue(chunks[0]["text"].endswith("classroom,"))
        self.assertEqual(" ".join(item["text"] for item in chunks), SENTENCE)
        self.assertLess(chunks[0]["end"], chunks[1]["start"] + 0.01)

    def test_build_chunks_skips_short_sentence(self):
        data = cet6_paper.sentence_words(
            PAPER, "Section A 长对话", "Conversation 1", 2)
        self.assertEqual(
            cet6_chunk.build_chunks(data["text"], data["words"],
                                    data["clip_start"], data["end"]), [])

    def test_queue_only_returns_long_sentences(self):
        data = cet6_chunk.queue(self.conn, limit=8)
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertEqual(item["sentence"], 1)
        self.assertNotIn("chunks", item)
        self.assertTrue(
            urllib.parse.unquote(item["audio_url"]).endswith("/句子/01.mp3"))

    def test_attempt_scores_chunks_and_creates_cards(self):
        data = cet6_chunk.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "sentence": 1,
            "answer": "When I teach in the classroom, we often talk about "
                      "and what leads to success.",
            "duration_s": 50})
        self.assertLess(data["score"], 1.0)
        self.assertGreaterEqual(data["chunk_count"], 2)
        self.assertGreaterEqual(data["cards_created"], 1)
        self.assertTrue(
            urllib.parse.unquote(data["audio_url"]).endswith("/句子/01.mp3"))
        cards = store.wrong_items(self.conn, source="cet6_chunk", limit=20)
        self.assertGreaterEqual(len(cards), 1)

    def test_attempt_unknown_sentence_returns_lookup_error(self):
        with self.assertRaises(LookupError):
            cet6_chunk.attempt(self.conn, {
                "paper_id": "p1", "section": "Section A 长对话",
                "item": "Conversation 1", "sentence": 99, "answer": "x"})

    def test_stats(self):
        cet6_chunk.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "sentence": 1,
            "answer": SENTENCE})
        data = cet6_chunk.stats(self.conn)
        self.assertEqual(data["total_attempts"], 1)
        self.assertEqual(data["sentences"], 1)
        self.assertEqual(data["avg_score"], 1.0)
        self.assertEqual(data["by_section"]["A"]["avg_score"], 1.0)

    def test_stats_empty(self):
        data = cet6_chunk.stats(self.conn)
        self.assertEqual(data["total_attempts"], 0)
        self.assertEqual(data["avg_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
