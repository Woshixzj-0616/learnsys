# -*- coding: utf-8 -*-
"""B1 深链桥：待跳转队列与 /api/ui/navigate 两个接口。"""
from __future__ import annotations

import os
import sys
import unittest

from fastapi.testclient import TestClient

from learnsys.server.app import create_app
from learnsys.server.nav_bridge import NavBridge, clean_href

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class CleanHrefTest(unittest.TestCase):
    def test_接受页内深链(self):
        self.assertEqual(clean_href(" #/quiz?focus=词汇 "), "#/quiz?focus=词汇")
        self.assertEqual(clean_href("#/ask/12"), "#/ask/12")

    def test_拒绝外部地址与协议相对(self):
        for bad in ("http://example.com", "https://x", "//evil", "#//evil",
                    "javascript:alert(1)"):
            with self.subTest(href=bad):
                with self.assertRaises(ValueError):
                    clean_href(bad)

    def test_拒绝过长与控制字符(self):
        with self.assertRaises(ValueError):
            clean_href("#/" + "a" * 600)
        with self.assertRaises(ValueError):
            clean_href("#/a\nb")

    def test_空值(self):
        with self.assertRaises(ValueError):
            clean_href("")
        with self.assertRaises(ValueError):
            clean_href(None)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class BridgeTest(unittest.TestCase):
    def test_序号递增且返回最新(self):
        bridge = NavBridge()
        self.assertEqual(bridge.set("#/a"), 1)
        self.assertEqual(bridge.set("#/b"), 2)
        data = bridge.snapshot()
        self.assertEqual(data["seq"], 2)
        self.assertEqual(data["href"], "#/b")
        self.assertEqual(len(data["server"]), 8)

    def test_过期后href为空但序号保留(self):
        clock = FakeClock()
        bridge = NavBridge(ttl=30, clock=clock)
        bridge.set("#/quiz")
        clock.now += 30.0
        self.assertEqual(bridge.snapshot()["href"], "#/quiz")
        clock.now += 0.1
        data = bridge.snapshot()
        self.assertEqual(data["href"], "")
        self.assertEqual(data["seq"], 1)

    def test_过期后再次写入恢复(self):
        clock = FakeClock()
        bridge = NavBridge(ttl=5, clock=clock)
        bridge.set("#/a")
        clock.now += 10
        self.assertEqual(bridge.set("#/b"), 2)
        self.assertEqual(bridge.snapshot()["href"], "#/b")

    def test_服务id稳定(self):
        bridge = NavBridge()
        self.assertEqual(bridge.server, bridge.snapshot()["server"])


class NavigateRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(token=TOKEN))

    def test_写入后读取(self):
        res = self.client.post("/api/ui/navigate", json={"href": "#/wrongbook"},
                               headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        res = self.client.get("/api/ui/navigate", headers=AUTH)
        body = res.json()
        self.assertEqual(body["href"], "#/wrongbook")
        self.assertEqual(body["seq"], 1)
        self.assertEqual(len(body["server"]), 8)

    def test_格式错返回400且不覆盖上一条(self):
        self.client.post("/api/ui/navigate", json={"href": "#/good"}, headers=AUTH)
        res = self.client.post("/api/ui/navigate", json={"href": "https://bad"},
                               headers=AUTH)
        self.assertEqual(res.status_code, 400)
        self.assertIn("深链", res.json()["detail"])
        self.assertEqual(self.client.get("/api/ui/navigate", headers=AUTH).json()["href"],
                         "#/good")

    def test_没有令牌返回403(self):
        self.assertEqual(self.client.post("/api/ui/navigate", json={"href": "#/a"})
                         .status_code, 403)
        self.assertEqual(self.client.get("/api/ui/navigate").status_code, 403)

    def test_跨源被拒(self):
        res = self.client.post("/api/ui/navigate", json={"href": "#/a"},
                               headers={**AUTH, "Origin": "https://evil.example"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    unittest.main(verbosity=2)
