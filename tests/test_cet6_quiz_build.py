# -*- coding: utf-8 -*-
"""六级做题题库生成：原文匹配、题号挂载、无数据桩。"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import unittest

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "cet6_quiz_build.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("cet6_quiz_build_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_db(path: pathlib.Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE question_group (id INTEGER PRIMARY KEY, source_file TEXT, "
        "title TEXT, transcript TEXT, group_type TEXT);"
        "CREATE TABLE question (id INTEGER PRIMARY KEY, group_id INTEGER, "
        "q_number INTEGER, correct_answer TEXT, explanation TEXT);"
        "CREATE TABLE option (id INTEGER PRIMARY KEY, question_id INTEGER, "
        "label TEXT, text TEXT);")
    conn.execute(
        "INSERT INTO question_group VALUES (1, '2023-06-CET6-1.pdf', "
        "'Listening: Questions 1 to 4', 'hello how are you today', 'listening')")
    for number, answer in ((1, "B"), (2, "C"), (3, "A"), (4, "D")):
        conn.execute(
            "INSERT INTO question VALUES (?, 1, ?, ?, ?)",
            (number, number, answer, f"解析 {number}"))
        for offset, label in enumerate("ABCD"):
            conn.execute(
                "INSERT INTO option (question_id, label, text) VALUES (?, ?, ?)",
                (number, label, f"option {label} {number}"))
    conn.commit()
    conn.close()


def _write_paper(root: pathlib.Path, name: str, en: str = "hello how are you today") -> None:
    paper = root / name
    paper.mkdir(parents=True)
    data = {
        "title": name,
        "sections": [{
            "letter": "A", "name": "Section A",
            "items": [{
                "index": 1, "title": "Conversation 1",
                "sentences": [{"i": 1, "en": en}],
                "question_items": [{"i": 1, "number": 1,
                                    "en": "What does the man say?"}],
            }],
        }],
    }
    (paper / "data.js").write_text(
        "window.PAPER = " + json.dumps(data, ensure_ascii=False) + ";",
        encoding="utf-8")


class Cet6QuizBuildTest(unittest.TestCase):
    def setUp(self):
        self.tool = _load_tool()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "quiz.db"
        _write_db(self.db)
        self.papers = self.root / "试卷"
        _write_paper(self.papers, "2023年06月测试卷")
        _write_paper(self.papers, "2018年06月旧卷", en="completely different words")

    def test_build_maps_by_transcript_and_number(self):
        content, report = self.tool.build(self.papers, self.db)
        self.assertIn("2023年06月测试卷", content["papers"])
        paper = content["papers"]["2023年06月测试卷"]
        self.assertEqual(paper["source_file"], "2023-06-CET6-1.pdf")
        question = paper["items"]["A-1"]["questions"]["1"]
        self.assertEqual(question["answer"], "B")
        self.assertEqual([opt["label"] for opt in question["options"]],
                         list("ABCD"))
        self.assertNotIn("2018年06月旧卷", content["papers"])

    def test_sidecars_write_data_and_stub(self):
        content, _ = self.tool.build(self.papers, self.db)
        written = self.tool.write_sidecars(self.papers, content)
        self.assertEqual(written, 2)
        data = (self.papers / "2023年06月测试卷" / "quiz.js").read_text(
            encoding="utf-8")
        self.assertIn("window.QUIZ", data)
        stub = (self.papers / "2018年06月旧卷" / "quiz.js").read_text(
            encoding="utf-8")
        self.assertIn("题库覆盖 2019 年及以后", stub)


if __name__ == "__main__":
    unittest.main()
