# -*- coding: utf-8 -*-
"""Qt 深链工具：href 归一化、URL 拼装、写队列（不发真实网络）。"""
from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from learnsys.ask.desktop import deep_link


class HashTargetTest(unittest.TestCase):
    def test_页内深链原样返回(self):
        self.assertEqual(deep_link.hash_target("#/quiz"), "#/quiz")
        self.assertEqual(deep_link.hash_target("#/ask/12?x=1"), "#/ask/12?x=1")

    def test_裸插件名补前缀(self):
        self.assertEqual(deep_link.hash_target("wrongbook"), "#/wrongbook")
        self.assertEqual(deep_link.hash_target("#wrongbook"), "#/wrongbook")

    def test_空值回今日(self):
        self.assertEqual(deep_link.hash_target(""), "#/today")
        self.assertEqual(deep_link.hash_target(None), "#/today")

    def test_外部地址与根路径不走队列(self):
        self.assertEqual(deep_link.hash_target("http://example.com/x"), "")
        self.assertEqual(deep_link.hash_target("/#/quiz"), "")


class WorkbenchUrlTest(unittest.TestCase):
    def test_深链落在目标页(self):
        self.assertEqual(deep_link.workbench_url(8765, "#/quiz?focus=词汇"),
                         "http://127.0.0.1:8765/#/quiz?focus=词汇")
        self.assertEqual(deep_link.workbench_url(8765, "wrongbook"),
                         "http://127.0.0.1:8765/#/wrongbook")

    def test_外部地址原样(self):
        self.assertEqual(deep_link.workbench_url(8765, "https://example.com/x"),
                         "https://example.com/x")

    def test_根路径拼端口(self):
        self.assertEqual(deep_link.workbench_url(8766, "/#/today"),
                         "http://127.0.0.1:8766/#/today")


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


class PostNavigateTest(unittest.TestCase):
    def test_健康接口取令牌后带令牌写队列(self):
        health = FakeResponse(json.dumps({"token": "t-1"}).encode("utf-8"))
        result = FakeResponse(b'{"ok": true, "seq": 1}')
        seen = []

        def fake_urlopen(request, timeout=0):
            seen.append(request)
            return health if len(seen) == 1 else result

        with mock.patch.object(deep_link.urllib.request, "urlopen", fake_urlopen):
            self.assertTrue(deep_link.post_navigate(8765, "#/quiz"))

        self.assertEqual(seen[0], "http://127.0.0.1:8765/api/health")
        self.assertEqual(seen[1].full_url, "http://127.0.0.1:8765/api/ui/navigate")
        payload = json.loads(seen[1].data.decode("utf-8"))
        self.assertEqual(payload, {"href": "#/quiz"})
        headers = {key.lower(): value for key, value in seen[1].headers.items()}
        self.assertEqual(headers["x-learnsys-token"], "t-1")

    def test_网络失败返回False(self):
        with mock.patch.object(deep_link.urllib.request, "urlopen",
                               side_effect=OSError("连不上")):
            self.assertFalse(deep_link.post_navigate(8765, "#/quiz"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
