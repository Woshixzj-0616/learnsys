# -*- coding: utf-8 -*-
"""六级真题自评：题干解析、队列优先级、提交校验、分段统计。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import urllib.parse
from unittest import mock

from learnsys import config, store
from learnsys.services.cet6 import exam as cet6_exam, paper as cet6_paper

PAPER = "卷一"


def _write_paper(root: pathlib.Path) -> None:
    paper = root / "试卷" / PAPER
    base = paper / "Section-A-长对话" / "01-Conversation-1"
    (base / "问题").mkdir(parents=True)
    (base / "正文.mp3").write_bytes(b"")
    (base / "题目.mp3").write_bytes(b"")
    for index in (1, 2):
        (base / "问题" / f"{index:02d}.mp3").write_bytes(b"")
    (base / "句子").mkdir()
    (base / "句子" / "01.mp3").write_bytes(b"")
    data = {
        "paper_id": "卷一_100",
        "title": PAPER,
        "sections": [{
            "letter": "A",
            "name": "Section A 长对话",
            "items": [{
                "index": 1,
                "title": "Conversation 1",
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
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")
    # B/C 段只有目录和音频，data.js 里没有题干：队列应跳过
    for section, item in (("Section-B-短文理解", "Passage-1"),
                          ("Section-C-讲座-讲话", "Recording-1")):
        folder = paper / section / f"01-{item}"
        (folder / "问题").mkdir(parents=True)
        (folder / "正文.mp3").write_bytes(b"")
        (folder / "题目.mp3").write_bytes(b"")


class ExamServiceTest(unittest.TestCase):
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
        seed(self.conn)

    def test_paper_questions_and_audio(self):
        questions = cet6_paper.item_questions(
            PAPER, "Section A 长对话", "Conversation 1")
        self.assertEqual([item["number"] for item in questions], [1, 2])
        unquote = urllib.parse.unquote
        self.assertTrue(unquote(questions[0]["audio_url"]).endswith("/问题/01.mp3"))
        audio = cet6_paper.item_audio(PAPER, "Section A 长对话", "Conversation 1")
        self.assertTrue(unquote(audio["content"]).endswith("/正文.mp3"))
        self.assertTrue(unquote(audio["questions"]).endswith("/题目.mp3"))
        sentence = cet6_paper.audio_url(
            PAPER, "Section A 长对话", "Conversation 1", sentence=1)
        self.assertTrue(unquote(sentence).endswith("/句子/01.mp3"))

    def test_queue_prefers_a_before_c(self):
        data = cet6_exam.queue(self.conn, limit=1)
        self.assertEqual(data["count"], 1)
        item = data["items"][0]
        self.assertEqual(item["section"], "Section A 长对话")
        self.assertEqual(len(item["questions"]), 2)
        self.assertNotIn("transcript", item)

    def test_queue_skips_items_without_questions(self):
        # 卷一 B 段没有题干：队列里只有 A 和卷二 C
        data = cet6_exam.queue(self.conn, limit=3)
        sections = {item["section"] for item in data["items"]}
        self.assertEqual(sections, {"Section A 长对话", "Section C 讲座/讲话"})

    def test_queue_avoids_recent_attempts(self):
        cet6_exam.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [], "duration_s": 30})
        data = cet6_exam.queue(self.conn, limit=1)
        # A 段刚做过 → 排到最后；B 段没题干 → 跳过；轮到卷二 C
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["section"], "Section C 讲座/讲话")

    def test_attempt_scores_and_returns_transcript(self):
        data = cet6_exam.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [1], "duration_s": 45})
        self.assertEqual(data["question_count"], 2)
        self.assertEqual(data["correct_count"], 1)
        self.assertEqual(data["wrong"], [1])
        self.assertEqual(data["self_accuracy"], 0.5)
        self.assertEqual(data["transcript"], ["Hello there.", "Nice to meet you."])

    def test_attempt_dedupes_wrong_numbers(self):
        data = cet6_exam.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [2, 2, 2]})
        self.assertEqual(data["wrong"], [2])
        self.assertEqual(data["correct_count"], 1)

    def test_attempt_rejects_unknown_number(self):
        with self.assertRaises(ValueError):
            cet6_exam.attempt(self.conn, {
                "paper_id": "p1", "section": "Section A 长对话",
                "item": "Conversation 1", "wrong": [99]})

    def test_attempt_requires_synced_item(self):
        with self.assertRaises(LookupError):
            cet6_exam.attempt(self.conn, {
                "paper_id": "p1", "section": "Section A 长对话",
                "item": "Conversation 9", "wrong": []})

    def test_stats_by_section(self):
        cet6_exam.attempt(self.conn, {
            "paper_id": "p1", "section": "Section A 长对话",
            "item": "Conversation 1", "wrong": [1]})
        cet6_exam.attempt(self.conn, {
            "paper_id": "p2", "section": "Section C 讲座/讲话",
            "item": "Recording 1", "wrong": []})
        data = cet6_exam.stats(self.conn)
        self.assertEqual(data["total_attempts"], 2)
        self.assertEqual(data["questions"], 4)
        self.assertEqual(data["correct"], 3)
        self.assertEqual(data["self_accuracy"], 0.75)
        self.assertEqual(data["by_section"]["A"]["self_accuracy"], 0.5)
        self.assertEqual(data["by_section"]["C"]["self_accuracy"], 1.0)

    def test_stats_empty(self):
        data = cet6_exam.stats(self.conn)
        self.assertEqual(data["total_attempts"], 0)
        self.assertEqual(data["self_accuracy"], 0.0)
        self.assertEqual(data["by_section"], {})


def seed(conn):
    store.upsert_cet6_progress(
        conn, paper_id="p1", paper_title=PAPER,
        section="Section A 长对话", item="Conversation 1",
        rows=[{"sentence": 1, "en": "Hello there."},
              {"sentence": 2, "en": "Nice to meet you."}], done=[])
    store.upsert_cet6_progress(
        conn, paper_id="p1", paper_title=PAPER,
        section="Section B 短文理解", item="Passage 1",
        rows=[{"sentence": 1, "en": "A short passage."}], done=[])
    store.upsert_cet6_progress(
        conn, paper_id="p2", paper_title="卷二",
        section="Section C 讲座/讲话", item="Recording 1",
        rows=[{"sentence": 1, "en": "A lecture."},
              {"sentence": 2, "en": "More lecture."}], done=[])
    # 卷二 的题干/音频：让 C 段也能提交
    paper = pathlib.Path(config.cet6_dir()) / "试卷" / "卷二"
    base = paper / "Section-C-讲座-讲话" / "01-Recording-1"
    (base / "问题").mkdir(parents=True)
    (base / "正文.mp3").write_bytes(b"")
    (base / "题目.mp3").write_bytes(b"")
    for index in (1, 2):
        (base / "问题" / f"{index:02d}.mp3").write_bytes(b"")
    data = {
        "paper_id": "卷二_100", "title": "卷二",
        "sections": [{
            "letter": "C", "name": "Section C 讲座/讲话",
            "items": [{
                "index": 1, "title": "Recording 1",
                "paths": {
                    "content": "Section-C-讲座-讲话/01-Recording-1/正文.mp3",
                    "questions": "Section-C-讲座-讲话/01-Recording-1/题目.mp3",
                },
                "question_items": [
                    {"i": 1, "number": 19, "en": "What is said?"},
                    {"i": 2, "number": 20, "en": "Why is that?"},
                ],
            }],
        }],
    }
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
