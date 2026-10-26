# -*- coding: utf-8 -*-
"""训练提交生命周期：草稿、自动保存、提交、轮询、错误卡、二稿、重批。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.services import train_review, train_submissions as service
from learnsys.train import content

WRITING = ("I think part-time jobs are good because students can learn many "
           "things from them. This gives them useful experience. Working also "
           "teaches students how to manage their time.")


def writing_json(band: int = 12) -> str:
    return json.dumps({
        "band": band, "band_reason": "结构清楚，但搭配不自然。",
        "off_topic": False,
        "dimensions": {"content": 3, "structure": 3, "language": 2,
                       "idiomatic": 1},
        "errors": [
            {"type": "搭配", "severity": "严重", "quote": "learn many things",
             "fix": "gain practical experience", "why": "搭配不自然"},
            {"type": "语法", "severity": "一般", "quote": "students can learn",
             "fix": "students learn", "why": "可以更简洁"},
        ],
        "priorities": ["换成具体经验", "检查冠词", "补一个例子"],
        "rewrite_task": "只改搭配和冠词。",
    }, ensure_ascii=False)


class TrainSubmissionTest(unittest.TestCase):
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
        self.texts: list[str] = [writing_json()]
        self.calls = 0

        def fake_run(request, cfg=None, abort=None, **_kwargs):
            text = self.texts[min(self.calls, len(self.texts) - 1)]
            self.calls += 1
            yield AgentEvent("done", data={
                "text": text,
                "usage": {"input_tokens": 12, "output_tokens": 4}})

        self.patch_run = mock.patch.object(train_review.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)

    def _wait(self, sub_id: int, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            conn = store.connect()
            try:
                row = service.detail(conn, sub_id)
            finally:
                conn.close()
            if row["status"] != "reviewing":
                return row
            time.sleep(0.03)
        raise AssertionError("批改没有在超时内结束")

    def test_draft_submit_review_and_cards(self):
        conn = store.connect()
        try:
            sub = service.create_submission(conn, kind="writing", prompt_id="w01")
            self.assertEqual(sub["status"], "draft")
            self.assertNotIn("model_essay", sub)
            sub = service.patch_submission(
                conn, sub["id"], text=WRITING, duration_s=35,
                flags={"pasted_chars": 0, "left_seconds": 0})
            self.assertEqual(sub["status"], "draft")
            self.assertGreater(sub["word_count"], 10)

            submitted = service.submit_submission(conn, sub["id"])
            self.assertEqual(submitted["status"], "reviewing")
        finally:
            conn.close()

        row = self._wait(sub["id"])
        self.assertEqual(row["status"], "reviewed")
        self.assertEqual(row["band"], 12)
        self.assertEqual(row["error_count"], 2)
        self.assertEqual(row["serious_count"], 1)
        self.assertEqual(row["review"]["band"], 12)
        self.assertIn("model_essay", row)
        self.assertTrue(row["review"].get("cards"))

        conn = store.connect()
        try:
            wrong = store.wrong_items(conn, source="writing")
            self.assertEqual(len(wrong), 1)
            self.assertEqual(wrong[0]["source"], "writing")
            self.assertEqual(wrong[0]["auto"], 1)
            self.assertIn("learn many things", wrong[0]["question"])
            detail = service.detail(conn, sub["id"])
            self.assertEqual(detail["band"], 12)
            history = service.history(conn, "writing")
            self.assertEqual(history["count"], 1)
            self.assertEqual(history["items"][0]["title"], "大学生该不该做兼职")
            detail = service.prompt_detail("writing", "w01")
            self.assertNotIn("model_essay", detail)
            self.assertNotIn("upgrades", detail)
        finally:
            conn.close()

    def test_lead_only_submission_is_rejected(self):
        lead = content.pack("writing", "w13")["lead_sentence"]
        conn = store.connect()
        try:
            sub = service.create_submission(
                conn, kind="writing", prompt_id="w13")
            service.patch_submission(conn, sub["id"], text=lead)
            with self.assertRaises(ValueError):
                service.submit_submission(conn, sub["id"])

            service.patch_submission(conn, sub["id"], text=f"{lead}\n\n{WRITING}")
            self.assertEqual(
                service.submit_submission(conn, sub["id"])["status"],
                "reviewing")

            deleted = service.create_submission(
                conn, kind="writing", prompt_id="w13")
            service.patch_submission(conn, deleted["id"], text=WRITING)
            self.assertEqual(
                service.submit_submission(conn, deleted["id"])["status"],
                "reviewing")
        finally:
            conn.close()
        self._wait(sub["id"])
        self._wait(deleted["id"])

    def test_rewrite_links_parent_and_external_score(self):
        conn = store.connect()
        try:
            first = service.create_submission(conn, kind="writing", prompt_id="w01")
            service.patch_submission(conn, first["id"], text=WRITING)
            service.submit_submission(conn, first["id"])
        finally:
            conn.close()
        self._wait(first["id"])

        conn = store.connect()
        try:
            second = service.create_submission(
                conn, kind="writing", prompt_id="w01", parent_id=first["id"])
            self.assertEqual(second["mode"], "rewrite")
            self.assertEqual(second["text"], WRITING)
            self.assertEqual(second["parent"]["priorities"],
                             ["换成具体经验", "检查冠词", "补一个例子"])
            service.patch_submission(conn, second["id"], text=WRITING + " More detail.")
            service.submit_submission(conn, second["id"])
        finally:
            conn.close()
        row = self._wait(second["id"])
        self.assertEqual(row["parent"]["id"], first["id"])
        self.assertEqual(row["parent"]["band"], 12)

        conn = store.connect()
        try:
            scored = service.set_external_score(conn, second["id"], 10.5)
            self.assertEqual(scored["external_score"], 10.5)
            with self.assertRaises(ValueError):
                service.set_external_score(conn, second["id"], 20)
        finally:
            conn.close()

    def test_translation_terms_go_to_vocab(self):
        pack = content.pack("translation", "t01")
        self.texts = [json.dumps({
            "band": 10, "band_reason": "信息基本完整。",
            "info_points": {"missing": []},
            "dimensions": {"coverage": 4, "accuracy": 3, "fluency": 3,
                           "terminology": 2},
            "errors": [
                {"type": "术语", "severity": "严重", "quote": "Spring Festival",
                 "fix": "the Spring Festival", "why": "专有名词需要冠词"},
            ],
        }, ensure_ascii=False)]
        conn = store.connect()
        try:
            sub = service.create_submission(
                conn, kind="translation", prompt_id="t01")
            service.patch_submission(conn, sub["id"], text=pack["reference"])
            service.submit_submission(conn, sub["id"])
        finally:
            conn.close()
        row = self._wait(sub["id"])
        self.assertEqual(row["status"], "reviewed")
        self.assertEqual(row["band"], 10)
        self.assertTrue(row["segments"])
        self.assertTrue(row["reference"])
        self.assertTrue(row["info_point_table"])
        conn = store.connect()
        try:
            vocab = store.list_vocab(conn, query="Spring Festival")
            self.assertEqual(vocab["count"], 1)
            wrong = store.wrong_items(conn, source="translation")
            self.assertEqual(len(wrong), 1)
        finally:
            conn.close()

    def test_failed_job_marks_submission_failed(self):
        def bad_run(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("error", text="模型挂了")

        with mock.patch.object(train_review.agent, "run", bad_run):
            conn = store.connect()
            try:
                sub = service.create_submission(
                    conn, kind="writing", prompt_id="w01")
                service.patch_submission(conn, sub["id"], text=WRITING)
                service.submit_submission(conn, sub["id"])
            finally:
                conn.close()
            row = self._wait(sub["id"])
        self.assertEqual(row["status"], "failed")
        self.assertIn("模型挂了", row["error"])
        # 失败后可以改正文再提交
        conn = store.connect()
        try:
            patched = service.patch_submission(
                conn, sub["id"], text=WRITING + " Another sentence.")
            self.assertEqual(patched["status"], "failed")
        finally:
            conn.close()

    def test_review_already_submitted_is_rejected(self):
        conn = store.connect()
        try:
            sub = service.create_submission(conn, kind="writing", prompt_id="w01")
            service.patch_submission(conn, sub["id"], text=WRITING)
            service.submit_submission(conn, sub["id"])
        finally:
            conn.close()
        self._wait(sub["id"])
        conn = store.connect()
        try:
            with self.assertRaises(ValueError):
                service.submit_submission(conn, sub["id"])
        finally:
            conn.close()

    def test_review_force_creates_new_result(self):
        conn = store.connect()
        try:
            sub = service.create_submission(conn, kind="writing", prompt_id="w01")
            service.patch_submission(conn, sub["id"], text=WRITING)
            service.submit_submission(conn, sub["id"])
        finally:
            conn.close()
        first = self._wait(sub["id"])
        self.calls = 0
        self.texts = [writing_json(13)]
        conn = store.connect()
        try:
            redoing = service.review_submission(conn, sub["id"])
            self.assertEqual(redoing["status"], "reviewing")
        finally:
            conn.close()
        second = self._wait(sub["id"])
        self.assertEqual(second["band"], 13)
        self.assertNotEqual(second["result_id"], first["result_id"])


if __name__ == "__main__":
    unittest.main()
