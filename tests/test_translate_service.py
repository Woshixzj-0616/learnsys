# -*- coding: utf-8 -*-
"""翻译服务：单词/句子解析、缓存命中、批量、失败降级。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent.events import AgentEvent
from learnsys.services import translate


def fake_run(request, cfg=None, abort=None, **_kwargs):
    prompt = request.message
    if "逐句" in prompt or "句子编号" in prompt:
        text = json.dumps({"1": "第一句", "2": "第二句"}, ensure_ascii=False)
    elif "音标" in prompt:
        text = json.dumps({"translation": "子网划分", "meaning": "把网络划成子网",
                           "phonetic": "/ˈsʌbnetɪŋ/"}, ensure_ascii=False)
    else:
        text = json.dumps({"translation": "译文"}, ensure_ascii=False)
    yield AgentEvent("done", data={"text": text,
                                   "usage": {"input_tokens": 5, "output_tokens": 2}})


class TranslateServiceTest(unittest.TestCase):
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
        self.patch_run = mock.patch.object(translate.agent, "run", fake_run)
        self.patch_run.start()
        self.addCleanup(self.patch_run.stop)

    def test_word_translation_and_cache(self):
        first = translate.translate(
            "subnetting", kind="word",
            context={"sentence": "Subnetting divides a network."})
        self.assertEqual(first["translation"], "子网划分")
        self.assertIn("phonetic", first)
        self.assertFalse(first["cached"])
        second = translate.translate(
            "subnetting", kind="word",
            context={"sentence": "Subnetting divides a network."})
        self.assertTrue(second["cached"])

    def test_context_changes_word_cache_key(self):
        translate.translate("bank", kind="word", context={"sentence": "river bank"})
        other = translate.translate("bank", kind="word",
                                    context={"sentence": "bank account"})
        self.assertFalse(other["cached"])

    def test_sentence_batch_and_cache(self):
        sentences = [{"i": 1, "en": "Hello."}, {"i": 2, "en": "World."}]
        first = translate.translate_sentences(
            sentences, paper_id="p1", section="Section A", item="C1")
        self.assertEqual(first["items"]["1"]["translation"], "第一句")
        self.assertEqual(first["cached"], 0)
        second = translate.translate_sentences(
            sentences, paper_id="p1", section="Section A", item="C1")
        self.assertEqual(second["cached"], 2)

    def test_failure_returns_chinese_error_not_raise(self):
        def broken(request, cfg=None, abort=None, **_kwargs):
            yield AgentEvent("error", text="模型挂了")

        with mock.patch.object(translate.agent, "run", broken):
            result = translate.translate("hello", kind="word")
        self.assertEqual(result["translation"], "")
        self.assertEqual(result["error"], "翻译服务暂时不可用")

    def test_empty_text(self):
        self.assertIn("error", translate.translate("", kind="word"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
