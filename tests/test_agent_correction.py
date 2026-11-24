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
from learnsys.agent import correction, prompts
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


class NegationDetectTest(unittest.TestCase):
    def test_user_negates_premise(self):
        for text in ("但是这个文件我根本没有写过，我也不会写啊",
                     "但是我的是虚拟机不是靶机",
                     "我都和你说了没有，你听不懂吗",
                     "这个不是我做的"):
            with self.subTest(text=text):
                self.assertTrue(correction.negation(text))

    def test_ordinary_questions_are_not_negations(self):
        for text in ("帮我讲一下哈希表", "这个思路可行吗", "rsync 怎么定位错误", ""):
            with self.subTest(text=text):
                self.assertFalse(correction.negation(text))


class ExclusionListTest(unittest.TestCase):
    def test_collects_negated_sentences_from_history(self):
        history = [
            ("Admin.jsp是什么", "……"),
            ("但是这个文件我根本没有写过，我也不会写啊", "……"),
            ("但是我的是虚拟机不是靶机", "……"),
        ]
        items = correction.exclusions(history, "我都和你说了没有，你听不懂吗")
        self.assertEqual(len(items), 3)
        self.assertIn("我根本没有写过", items[0])
        self.assertIn("不是靶机", items[1])
        self.assertIn("都和你说了没有", items[2])

    def test_ordinary_history_has_no_exclusions(self):
        history = [("rsync 怎么定位错误", "……"), ("那快排呢", "……")]
        self.assertEqual(correction.exclusions(history, "讲讲哈希表"), [])


class NegationPromptTest(unittest.TestCase):
    def _system(self, message: str, history=None) -> str:
        return prompts.build_system("explain", agent_profile="assistant",
                                    message=message, history=history)

    def test_negation_turn_injects_exclusion_rule(self):
        system = self._system("但是我的是虚拟机不是靶机")
        self.assertIn("【本轮是纠错/否定轮】", system)
        self.assertIn("已排除", system)

    def test_ordinary_turn_does_not_inject(self):
        system = self._system("哈希表怎么解决冲突")
        self.assertNotIn("【本轮是纠错/否定轮】", system)

    def test_prefix_notation_rule_is_always_present(self):
        self.assertIn("前缀表达式", self._system("哈希表怎么解决冲突"))

    def test_history_exclusions_injected_even_without_current_negation(self):
        system = self._system(
            "那我该怎么办", history=[("但是这个文件我根本没有写过，我也不会写啊", "……")])
        self.assertIn("用户已明确否定过的原话", system)
        self.assertIn("我根本没有写过", system)


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
