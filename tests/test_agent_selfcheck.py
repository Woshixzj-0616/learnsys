# -*- coding: utf-8 -*-
"""证据台账的只读辅助：URL 集合、工具是否调用过。"""
from __future__ import annotations

import unittest

from learnsys.agent.selfcheck import Evidence, verify


class EvidenceHelpersTest(unittest.TestCase):
    def test_urls_collects_http_links(self):
        evidence = Evidence()
        evidence.add("web_search", {},
                     "结果：https://nginx.org/en/docs/ 和 http://example.com/a。")
        self.assertIn("https://nginx.org/en/docs/", evidence.urls())

    def test_urls_empty_without_results(self):
        self.assertEqual(Evidence().urls(), set())

    def test_has_tool_by_name(self):
        evidence = Evidence()
        evidence.add("run_code", {}, "exit 0")
        self.assertTrue(evidence.has_tool("run_code"))
        self.assertFalse(evidence.has_tool("web_search"))

    def test_has_tool_empty(self):
        self.assertFalse(Evidence().has_tool("run_code"))


class VerifyUrlTest(unittest.TestCase):
    def test_known_url_passes(self):
        evidence = Evidence()
        evidence.add("web_search", {}, "结果：https://nginx.org/en/docs/")
        self.assertEqual(
            verify("来源：https://nginx.org/en/docs/", evidence), [])

    def test_unknown_url_is_flagged_when_web_used(self):
        evidence = Evidence()
        evidence.add("web_search", {}, "结果：https://nginx.org/en/docs/")
        issues = verify("来源：https://fake.example/x", evidence)
        self.assertTrue(any("没读过" in item for item in issues))

    def test_web_claim_without_url_is_flagged(self):
        evidence = Evidence()
        evidence.add("run_code", {}, "ok")
        issues = verify("网上查到 https://fake.example/x", evidence)
        self.assertTrue(any("没读过" in item for item in issues))

    def test_casual_link_is_not_flagged(self):
        evidence = Evidence()
        evidence.add("run_code", {}, "ok")
        self.assertEqual(verify("示例见 https://example.com/", evidence), [])


class VerifyWebDateTest(unittest.TestCase):
    def _evidence(self, date: str = "2026-11-24") -> Evidence:
        evidence = Evidence()
        evidence.add("web_search", {},
                     f"搜索「python」共 1 条：\n[1] Python\n"
                     f"    https://www.python.org/downloads/\n"
                     f"引用时用 [编号] + 网址 + 读取日期（{date}）。")
        return evidence

    def test_known_web_date_passes(self):
        self.assertEqual(
            verify("来源：https://www.python.org/downloads/"
                   "（读取日期：2026-11-24）", self._evidence()), [])

    def test_fabricated_web_date_is_flagged(self):
        issues = verify("来源：https://www.python.org/downloads/"
                        "（读取日期：2026-11-20）", self._evidence())
        self.assertTrue(any("日期" in item for item in issues))

    def test_date_without_web_tools_is_not_checked(self):
        evidence = Evidence()
        evidence.add("run_code", {}, "ok")
        self.assertEqual(verify("2026-11-24 学了 TCP", evidence), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
