# -*- coding: utf-8 -*-
"""P35.3：用户纠正轮识别，并让 Web 问答本轮升强模型。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import correction
from learnsys.agent.events import AgentEvent
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class CorrectionDetectTest(unittest.TestCase):
    def test_clear_corrections(self):
        for text in ("我说的是哈希表，不是栈", "你听不懂吗", "不对，是另一道题",
                     "答非所问，我问的是 rsync", "你理解错了"):
            with self.subTest(text=text):
                self.assertTrue(correction.detect(text))

    def test_normal_followups_are_not_corrections(self):
        for text in ("这样不对吗？", "帮我讲一下", "这个方法有什么坑", ""):
            with self.subTest(text=text):
                self.assertFalse(correction.detect(text))


class ChatCorrectionDeepTest(unittest.TestCase):
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
        self.root_patch = mock.patch.object(
            app_config, "DATA_ROOT", pathlib.Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.client = TestClient(create_app(token=TOKEN))
        self.seen = []

    def _post(self, message: str, surface: str = "ask"):
        def fake_run(request, cfg=None, abort=None, **_kwargs):
            self.seen.append(request)
            yield AgentEvent("done", data={"text": "答"})

        with mock.patch("learnsys.server.routes_agent.agent.run", fake_run):
            res = self.client.post("/api/agent/chat", headers=AUTH, json={
                "message": message, "surface": surface})
        self.assertEqual(res.status_code, 200)
        return self.seen[-1]

    def test_correction_turn_escalates(self):
        request = self._post("我说的是哈希表，不是栈")
        self.assertTrue(request.deep)

    def test_normal_turn_does_not_escalate(self):
        request = self._post("帮我讲一下哈希表")
        self.assertFalse(request.deep)

    def test_cet6_correction_does_not_escalate(self):
        request = self._post("我说的是听力那句", surface="cet6")
        self.assertFalse(request.deep)


if __name__ == "__main__":
    unittest.main()
