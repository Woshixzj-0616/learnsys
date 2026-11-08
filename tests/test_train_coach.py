# -*- coding: utf-8 -*-
"""写作/翻译提升提醒：二稿优先、弱项专项、每周整篇、每天不重复。"""
from __future__ import annotations

import datetime
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services.train import coach
from learnsys.services.train import submissions as service

TODAY = datetime.date.today().isoformat()


def _review(errors=None, priorities=None, rewrite_task=""):
    return {
        "band": 7,
        "band_reason": "测试用批改",
        "errors": errors or [],
        "priorities": priorities or ["改首句", "改术语"],
        "rewrite_task": rewrite_task,
    }


class CoachTest(unittest.TestCase):
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

    def _whole(self, kind="writing", prompt_id="w25", review=None):
        conn = store.connect()
        try:
            sub = service.create_submission(conn, kind=kind, prompt_id=prompt_id,
                                            mode="timed")
            service.patch_submission(conn, sub["id"], text="test text",
                                     duration_s=1800)
            store.set_submission_review(conn, sub["id"], band=7,
                                        review=review or _review(), result_id=0)
            return sub["id"]
        finally:
            conn.close()

    def _rewrite(self, parent_id, kind="writing", prompt_id="w25", draft=False):
        conn = store.connect()
        try:
            sub = service.create_submission(conn, kind=kind, prompt_id=prompt_id,
                                            parent_id=parent_id)
            service.patch_submission(conn, sub["id"], text="test text",
                                     duration_s=1800)
            if not draft:
                store.set_submission_review(conn, sub["id"], band=8,
                                            review=_review(), result_id=0)
            return sub["id"]
        finally:
            conn.close()

    def test_empty_base_pushes_weekly_whole(self):
        conn = store.connect()
        try:
            action = coach.build(conn, TODAY)
        finally:
            conn.close()
        self.assertEqual(action["kind"], "whole")
        self.assertEqual(action["href"], "#/cet6?tab=writing")

    def test_rewrite_first(self):
        sub_id = self._whole()
        conn = store.connect()
        try:
            action = coach.build(conn, TODAY)
        finally:
            conn.close()
        self.assertEqual(action["kind"], "rewrite")
        self.assertEqual(action["submission_id"], sub_id)
        self.assertIn(f"submission={sub_id}&rewrite=1", action["href"])

    def test_rewrite_draft_reused(self):
        sub_id = self._whole()
        first = self._rewrite(sub_id, draft=True)
        second = self._rewrite(sub_id, draft=True)
        self.assertEqual(first, second)

    def test_rewrite_draft_still_reminds(self):
        sub_id = self._whole()
        self._rewrite(sub_id, draft=True)
        conn = store.connect()
        try:
            action = coach.build(conn, TODAY)
        finally:
            conn.close()
        self.assertEqual(action["kind"], "rewrite")
        self.assertEqual(action["submission_id"], sub_id)

    def test_rewrite_done_moves_on(self):
        sub_id = self._whole()
        self._rewrite(sub_id)
        conn = store.connect()
        try:
            action = coach.build(conn, TODAY)
        finally:
            conn.close()
        # 今天已有写作提交，二稿也写了 -> 不再提醒
        self.assertIsNone(action)

    def test_skill_from_error_profile(self):
        sub_id = self._whole(review=_review(errors=[
            {"type": "术语", "severity": "严重", "quote": "test",
             "fix": "fixed", "why": "术语错"}]))
        self._rewrite(sub_id)
        conn = store.connect()
        try:
            with mock.patch.object(coach.train_plan, "today_activity",
                                   return_value={"writing": 0, "translation": 0,
                                                 "sentence": 0}):
                action = coach.build(conn, TODAY)
        finally:
            conn.close()
        self.assertEqual(action["kind"], "skill")
        self.assertEqual(action["skill"], "文化术语")
        self.assertIn("skill=", action["href"])

    def test_today_done_no_reminder(self):
        sub_id = self._whole(review=_review())
        self._rewrite(sub_id)
        conn = store.connect()
        try:
            with mock.patch.object(coach.train_plan, "today_activity",
                                   return_value={"writing": 1, "translation": 0,
                                                 "sentence": 0}):
                action = coach.build(conn, TODAY)
        finally:
            conn.close()
        self.assertIsNone(action)


if __name__ == "__main__":
    unittest.main()
