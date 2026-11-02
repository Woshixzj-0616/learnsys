# -*- coding: utf-8 -*-
"""纠音：笔记解析、目标词模糊匹配、词级音频片段、纠音池去重。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import urllib.parse
from unittest import mock

from learnsys import config, store
from learnsys.services import cet6_paper, cet6_pron

PAPER = "卷一"
SECTION = "Section A 长对话"
ITEM = "Conversation 1"
SENTENCE = "He had to combat the problem and sameness in the end."


def _write_paper(root: pathlib.Path) -> None:
    paper = root / "试卷" / PAPER
    base = paper / "Section-A-长对话" / "01-Conversation-1"
    (base / "句子").mkdir(parents=True)
    (base / "句子" / "01.mp3").write_bytes(b"")
    words = []
    moment = 10.0
    for index, token in enumerate(SENTENCE.split()):
        duration = 0.4 if token not in ("to", "the", "in") else 0.1
        words.append({"start": round(moment, 2), "end": round(moment + duration, 2),
                      "word": token})
        moment += duration + 0.05
    data = {
        "paper_id": "卷一_100", "title": PAPER,
        "sections": [{
            "letter": "A", "name": SECTION,
            "items": [{
                "index": 1, "title": ITEM,
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


class PronParseTest(unittest.TestCase):
    def test_extract_misheard_pair(self):
        self.assertEqual(
            cet6_pron.extract_note("combat没有听出，听成come back了，sameness没有听出"),
            [{"target": "combat", "heard_as": "come back", "kind": "misheard"},
             {"target": "sameness", "heard_as": "", "kind": "unknown"}])

    def test_extract_misheard_after_previous_target(self):
        self.assertEqual(
            cet6_pron.extract_note("rest理解成休息，infects听成effects"),
            [{"target": "infects", "heard_as": "effects", "kind": "misheard"}])

    def test_extract_multiple_english_runs(self):
        items = cet6_pron.extract_note(
            "assert，is analogous to，cafeteria.这几个没有听出")
        self.assertEqual([item["target"] for item in items],
                         ["assert", "is analogous to", "cafeteria"])

    def test_extract_linking(self):
        items = cet6_pron.extract_note(
            "consecutive知道意思但是不是很熟悉， from day to day, 连读没有听出")
        self.assertIn("from day to day", [item["target"] for item in items])
        target = next(item for item in items if item["target"] == "from day to day")
        self.assertEqual(target["kind"], "linking")

    def test_extract_vocab_and_after_trigger(self):
        items = cet6_pron.extract_note("elaborate不知道意思，没听出effects")
        kinds = {item["target"]: item["kind"] for item in items}
        self.assertEqual(kinds.get("elaborate"), "vocab")
        self.assertEqual(kinds.get("effects"), "unknown")

    def test_extract_ignores_structure_only_note(self):
        self.assertEqual(cet6_pron.extract_note("整句结构没理解，意思大概懂"), [])

    def test_match_target_exact_and_fuzzy(self):
        self.assertEqual(cet6_pron.match_target(SENTENCE, "combat"),
                         (3, 4, "combat"))
        self.assertEqual(cet6_pron.match_target(SENTENCE, "samness"),
                         (7, 8, "sameness"))


class PronAudioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        _write_paper(self.root)
        self.patch = mock.patch.object(config, "cet6_dir",
                                       return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_audio_segment_for_word(self):
        segment = cet6_pron.audio_segment(
            PAPER, SECTION, ITEM, 1, "combat")
        self.assertTrue(
            urllib.parse.unquote(segment["url"]).endswith("/句子/01.mp3"))
        self.assertGreaterEqual(segment["start"], 0.0)
        self.assertLess(segment["start"], segment["end"])

    def test_audio_segment_accounts_for_sentence_clip_lead(self):
        """句子 mp3 从「句首 - 0.2 秒」开始，偏移必须减去 clip_start。"""
        data = cet6_paper.sentence_words(PAPER, SECTION, ITEM, 1)
        self.assertAlmostEqual(data["clip_start"], 9.8, places=3)
        segment = cet6_pron.audio_segment(
            PAPER, SECTION, ITEM, 1, "combat")
        self.assertAlmostEqual(segment["start"], 1.20, places=2)
        self.assertAlmostEqual(segment["end"], 1.77, places=2)

    def test_audio_segment_fixes_typo(self):
        segment = cet6_pron.audio_segment(
            PAPER, SECTION, ITEM, 1, "samness")
        self.assertEqual(segment["corrected"], "sameness")

    def test_audio_segment_missing_paper_returns_empty(self):
        self.assertEqual(
            cet6_pron.audio_segment("不存在", SECTION, ITEM, 1, "combat"), {})


class PronPoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        _write_paper(self.root)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)
        self.patch = mock.patch.object(config, "cet6_dir",
                                       return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        store.upsert_cet6_progress(
            self.conn, paper_id="p1", paper_title=PAPER,
            section=SECTION, item=ITEM,
            rows=[{"sentence": 1, "en": SENTENCE,
                   "note": "combat没有听出，听成come back了；sameness没有听出"}],
            done=[])

    def test_ensure_pool_dedupes_and_corrects_target(self):
        first = cet6_pron.ensure_pool(self.conn)
        second = cet6_pron.ensure_pool(self.conn)
        self.assertGreaterEqual(first, 2)
        self.assertEqual(second, 0)
        items = store.pron_candidates(self.conn, since="2000-01-01", limit=20)
        targets = {item["target"]: item for item in items}
        self.assertIn("combat", targets)
        self.assertEqual(targets["combat"]["heard_as"], "come back")
        self.assertEqual(targets["combat"]["kind"], "misheard")
        self.assertIn("sameness", targets)


if __name__ == "__main__":
    unittest.main()
