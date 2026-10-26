# -*- coding: utf-8 -*-
"""训练接口：鉴权、题库、草稿/自动保存/提交/轮询、重批、外部分数。"""
from __future__ import annotations

import datetime
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.server.app import create_app
from learnsys.services import train_review

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}
WRITING = ("I think part-time jobs are good because students can learn many "
           "things from them. This gives them useful experience.")
PAYLOAD = {
    "band": 12, "band_reason": "结构清楚，但搭配不自然。", "off_topic": False,
    "dimensions": {"content": 3, "structure": 3, "language": 2, "idiomatic": 1},
    "errors": [
        {"type": "搭配", "severity": "严重", "quote": "learn many things",
         "fix": "gain practical experience", "why": "搭配不自然"},
    ],
    "priorities": ["换成具体经验", "检查冠词", "补一个例子"],
    "rewrite_task": "只改搭配和冠词。",
}


def fake_run(request, cfg=None, abort=None, **_kwargs):
    yield AgentEvent("done", data={
        "text": json.dumps(PAYLOAD, ensure_ascii=False),
        "usage": {"input_tokens": 12, "output_tokens": 4}})


class TrainRoutesTest(unittest.TestCase):
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

    def _poll(self, sub_id: int, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.client.get(
                f"/api/cet6/train/submissions/{sub_id}", headers=AUTH).json()
            if data["status"] != "reviewing":
                return data
            time.sleep(0.03)
        raise AssertionError("接口轮询超时")

    def test_requires_token(self):
        self.assertEqual(
            self.client.get("/api/cet6/train/prompts").status_code, 403)
        self.assertEqual(
            self.client.post("/api/cet6/train/submissions",
                             json={"prompt_id": "w01"}).status_code, 403)

    def test_prompt_list_and_detail_hide_model_essay(self):
        data = self.client.get("/api/cet6/train/prompts",
                               params={"kind": "writing"}, headers=AUTH).json()
        self.assertEqual(data["kind"], "writing")
        self.assertEqual(len(data["items"]), 12)
        first = data["items"][0]
        self.assertEqual(first["id"], "w01")
        self.assertEqual(first["done"], 0)
        detail = self.client.get(
            "/api/cet6/train/prompts/w01", headers=AUTH).json()
        self.assertIn("prompt_en", detail)
        self.assertNotIn("model_essay", detail)
        self.assertNotIn("upgrades", detail)
        self.assertEqual(
            self.client.get("/api/cet6/train/prompts/nope",
                            headers=AUTH).status_code, 404)
        self.assertEqual(
            self.client.get("/api/cet6/train/prompts/w01",
                            params={"kind": "reading"},
                            headers=AUTH).status_code, 400)

    def test_full_writing_flow(self):
        created = self.client.post(
            "/api/cet6/train/submissions",
            json={"kind": "writing", "prompt_id": "w01", "mode": "timed"},
            headers=AUTH)
        self.assertEqual(created.status_code, 201)
        sub = created.json()
        self.assertEqual(sub["status"], "draft")

        patched = self.client.patch(
            f"/api/cet6/train/submissions/{sub['id']}",
            json={"text": WRITING, "duration_s": 40, "pasted_chars": 0},
            headers=AUTH)
        self.assertEqual(patched.status_code, 200)
        self.assertGreater(patched.json()["word_count"], 10)

        submitted = self.client.post(
            f"/api/cet6/train/submissions/{sub['id']}/submit",
            json={"pasted_chars": 25, "left_seconds": 12}, headers=AUTH)
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["status"], "reviewing")

        row = self._poll(sub["id"])
        self.assertEqual(row["status"], "reviewed")
        self.assertEqual(row["band"], 12)
        self.assertEqual(row["serious_count"], 1)
        self.assertTrue(row["review"]["errors"])
        self.assertIn("model_essay", row)
        self.assertLessEqual(row["flags"]["pasted_chars"], 25)
        self.assertEqual(row["flags"]["left_seconds"], 12)

        wrong = self.client.get("/api/wrongbook", params={"source": "writing"},
                                headers=AUTH).json()
        self.assertEqual(len(wrong["items"]), 1)
        history = self.client.get(
            "/api/cet6/train/submissions", params={"kind": "writing"},
            headers=AUTH).json()
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["items"][0]["band"], 12)
        listed = self.client.get(
            "/api/cet6/train/prompts", params={"kind": "writing"},
            headers=AUTH).json()["items"][0]
        self.assertEqual(listed["done"], 1)
        self.assertEqual(listed["last_band"], 12)

    def test_cannot_edit_after_review_and_can_review_again(self):
        sub = self.client.post(
            "/api/cet6/train/submissions",
            json={"prompt_id": "w01"}, headers=AUTH).json()
        self.client.patch(f"/api/cet6/train/submissions/{sub['id']}",
                          json={"text": WRITING}, headers=AUTH)
        self.client.post(f"/api/cet6/train/submissions/{sub['id']}/submit",
                         json={}, headers=AUTH)
        first = self._poll(sub["id"])
        self.assertEqual(
            self.client.patch(f"/api/cet6/train/submissions/{sub['id']}",
                              json={"text": "new text"}, headers=AUTH).status_code,
            400)
        redone = self.client.post(
            f"/api/cet6/train/submissions/{sub['id']}/review", headers=AUTH)
        self.assertEqual(redone.status_code, 200)
        self.assertEqual(redone.json()["status"], "reviewing")
        second = self._poll(sub["id"])
        self.assertNotEqual(second["result_id"], first["result_id"])

    def test_external_score(self):
        sub = self.client.post(
            "/api/cet6/train/submissions",
            json={"prompt_id": "w01"}, headers=AUTH).json()
        self.client.patch(f"/api/cet6/train/submissions/{sub['id']}",
                          json={"text": WRITING}, headers=AUTH)
        self.client.post(f"/api/cet6/train/submissions/{sub['id']}/submit",
                         json={}, headers=AUTH)
        self._poll(sub["id"])
        scored = self.client.post(
            f"/api/cet6/train/submissions/{sub['id']}/external-score",
            json={"score": 10.5}, headers=AUTH)
        self.assertEqual(scored.status_code, 200)
        self.assertEqual(scored.json()["external_score"], 10.5)
        bad = self.client.post(
            f"/api/cet6/train/submissions/{sub['id']}/external-score",
            json={"score": 99}, headers=AUTH)
        self.assertEqual(bad.status_code, 400)

    def test_manual_wrongbook_accepts_writing_source(self):
        data = self.client.post("/api/wrongbook", json={
            "source": "writing", "question": "改错：learn many things",
            "answer": "gain practical experience",
            "my_answer": "learn many things"}, headers=AUTH).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["item"]["source"], "writing")
        self.assertTrue(data["item"]["source_id"].startswith("writing:"))

    def test_plan_stats_events_and_xp(self):
        sub = self.client.post(
            "/api/cet6/train/submissions",
            json={"prompt_id": "w01", "mode": "practice"},
            headers=AUTH).json()
        self.client.patch(f"/api/cet6/train/submissions/{sub['id']}",
                          json={"text": WRITING, "duration_s": 60}, headers=AUTH)
        self.client.post(f"/api/cet6/train/submissions/{sub['id']}/submit",
                         json={}, headers=AUTH)
        self._poll(sub["id"])

        plan = self.client.get("/api/cet6/train/plan", headers=AUTH).json()
        self.assertEqual(plan["today"]["writing"], 1)
        self.assertEqual(plan["today"]["total"], 1)
        self.assertEqual(plan["streak"], 1)
        self.assertEqual(plan["task"]["kind"], "translation")
        self.assertEqual(plan["task"]["href"], "#/cet6?tab=translation")

        stats = self.client.get("/api/cet6/train/stats",
                                params={"days": 30}, headers=AUTH).json()
        self.assertEqual(stats["totals"]["submissions"], 1)
        self.assertEqual(stats["by_kind"]["writing"]["submissions"], 1)
        self.assertEqual(stats["by_kind"]["writing"]["avg_band"], 12)
        self.assertEqual(stats["by_kind"]["writing"]["last_band"], 12)
        self.assertEqual(stats["error_types"][0]["type"], "搭配")
        self.assertEqual(stats["error_types"][0]["serious"], 1)
        self.assertEqual(stats["band_trend"][-1]["writing"], 12)

        errors = self.client.get("/api/cet6/train/errors",
                                 params={"kind": "writing"},
                                 headers=AUTH).json()
        self.assertEqual(errors["count"], 1)
        self.assertEqual(errors["items"][0]["source"], "writing")

        overview = self.client.get("/api/overview", headers=AUTH).json()
        self.assertEqual(overview["today"]["train"], 1)
        self.assertEqual(overview["today"]["train_writing"], 1)
        self.assertEqual(overview["today"]["xp"], 40)

        # 重批不重复记训练事件，也不重复给学习点
        self.client.post(f"/api/cet6/train/submissions/{sub['id']}/review",
                         headers=AUTH)
        self._poll(sub["id"])
        again = self.client.get("/api/overview", headers=AUTH).json()
        self.assertEqual(again["today"]["train"], 1)
        self.assertEqual(again["today"]["xp"], 40)

    def test_due_cards_can_be_reviewed_from_training(self):
        sub = self.client.post(
            "/api/cet6/train/submissions",
            json={"prompt_id": "w01"}, headers=AUTH).json()
        self.client.patch(f"/api/cet6/train/submissions/{sub['id']}",
                          json={"text": WRITING}, headers=AUTH)
        self.client.post(f"/api/cet6/train/submissions/{sub['id']}/submit",
                         json={}, headers=AUTH)
        self._poll(sub["id"])

        # 新卡默认明天到期；挪到昨天，模拟今天到期。
        conn = store.connect()
        try:
            yesterday = (datetime.date.today()
                         - datetime.timedelta(days=1)).isoformat()
            conn.execute("UPDATE wrong_items SET ts = ?",
                         (f"{yesterday} 09:00:00",))
            conn.commit()
        finally:
            conn.close()

        due = self.client.get("/api/cet6/train/errors",
                              params={"status": "due"}, headers=AUTH).json()
        self.assertEqual(due["count"], 1)
        card = due["items"][0]
        self.assertEqual(card["source"], "writing")
        plan = self.client.get("/api/cet6/train/plan", headers=AUTH).json()
        self.assertEqual(plan["due"]["total"], 1)
        self.assertEqual(plan["task"]["href"], "#/cet6?tab=review")

        rated = self.client.post(f"/api/review/wrong/{card['id']}",
                                 json={"rating": 3}, headers=AUTH)
        self.assertEqual(rated.status_code, 200)
        left = self.client.get("/api/cet6/train/errors",
                               params={"status": "due"}, headers=AUTH).json()
        self.assertEqual(left["count"], 0)


if __name__ == "__main__":
    unittest.main()
