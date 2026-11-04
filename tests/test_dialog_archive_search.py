"""对话总汇检索：片段、锚点、按锚点读原文、抽取过滤口径。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.services.dialog_archive import build as build_module
from learnsys.services.dialog_archive import search
from learnsys.services.dialog_archive.build import build_archive
from learnsys.services.dialog_archive.extract import _project, _strict
from learnsys.services.dialog_archive.model import Message, Session, Source


def _fake_source():
    def collect(cutoff_ts):
        return {"files": 1, "skipped": 0, "errors": 0, "sessions": [
            Session("codex", "s1", title="六级", at="2026-10-01T10:00:00",
                    path="f.jsonl", messages=[
                        Message("user", "我以后六级听力先看题再听"),
                        Message("assistant", "好的，先看题"),
                    ])]}
    return Source("codex", "Codex", "A", collect)


class TestArchiveSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with mock.patch.object(build_module, "SOURCES", [_fake_source()]):
            self.path = pathlib.Path(build_archive(self.tmp.name)["path"])

    def test_search_and_read(self):
        hits = search.search_archive(self.path, "六级 听力")
        self.assertEqual(len(hits), 1)
        self.assertIn("先看题", hits[0]["snippet"])
        item = search.read_message(self.path, hits[0]["anchor"])
        self.assertIn("六级听力先看题再听", item["text"])

    def test_no_match(self):
        self.assertEqual(search.search_archive(self.path, "不存在的词"), [])

    def test_latest_archive(self):
        self.assertEqual(search.latest_archive(self.tmp.name), self.path)


class TestExtractFilters(unittest.TestCase):
    def _chunk(self, text):
        return [{"role": "用户", "text": text, "anchor": "a"},
                {"role": "助手", "text": "回答", "anchor": "b"}]

    def test_strict_requires_first_person_preference(self):
        self.assertTrue(_strict(self._chunk("我以后每次都先复习")))
        self.assertFalse(_strict(self._chunk("今天学了快排")))

    def test_project_exclusion(self):
        self.assertTrue(_project(self._chunk("智能旅行的部署要发版")))
        self.assertFalse(_project(self._chunk("六级听力怎么练")))


if __name__ == "__main__":
    unittest.main()
