# -*- coding: utf-8 -*-
"""取证门控：什么时候必须联网取证、什么时候不干预。"""
from __future__ import annotations

import unittest

from learnsys.agent import evidence_gate, tools
from learnsys.agent.selfcheck import Evidence

CONFIG_TEXT = """server {
    listen 80;
    server_name example.com;
    root /usr/local/www/tm/public;
}"""


def evidence_with(*names) -> Evidence:
    evidence = Evidence()
    for name in names:
        evidence.add(name, {}, "结果")
    return evidence


class GateDecisionTest(unittest.TestCase):
    def test_off_does_nothing(self):
        decision = evidence_gate.decide(
            "nginx 最新版本是多少？", "", None, ops=True, ops_gate="off")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "none")

    def test_plain_question_does_nothing(self):
        decision = evidence_gate.decide(
            "什么是死锁？", "", None, ops=False, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "none")

    def test_user_provided_config_counts_as_evidence(self):
        decision = evidence_gate.decide(
            "这个配置为什么 80 不生效？", CONFIG_TEXT, None,
            ops=True, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "user_text")

    def test_user_provided_output_counts_as_evidence(self):
        decision = evidence_gate.decide(
            "这个报错什么意思？", "报错：nginx: [emerg] invalid port", None,
            ops=True, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "user_text")

    def test_version_question_without_evidence_needs_tools(self):
        decision = evidence_gate.decide(
            "nginx 最新稳定版是哪个版本？", "", Evidence(),
            ops=True, ops_gate="on")
        self.assertTrue(decision.needed)
        self.assertEqual(decision.kind, "tools_missing")

    def test_web_search_evidence_ends_gate(self):
        decision = evidence_gate.decide(
            "nginx 最新稳定版是哪个版本？", "", evidence_with("web_search"),
            ops=True, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "already_evidenced")

    def test_run_code_counts_as_evidence(self):
        decision = evidence_gate.decide(
            "Python 最新版本对这段代码怎么说？", "", evidence_with("run_code"),
            ops=True, ops_gate="on")
        self.assertEqual(decision.kind, "already_evidenced")

    def test_shell_question_does_not_force_search(self):
        decision = evidence_gate.decide(
            "80 端口被占用怎么办？", "", Evidence(), ops=True, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "none")

    def test_config_question_without_fact_words_does_not_force_search(self):
        decision = evidence_gate.decide(
            "改完 nginx.conf 页面没变化，一般要检查什么？", "", Evidence(),
            ops=True, ops_gate="on")
        self.assertFalse(decision.needed)
        self.assertEqual(decision.kind, "none")

    def test_nudge_mentions_tools_and_no_writes(self):
        text = evidence_gate.nudge_text()
        self.assertIn("先取证", text)
        self.assertIn("web_search", text)
        self.assertIn("fetch_url", text)
        self.assertIn("写操作", text)
        self.assertIn("最多 2 次", text)

    def test_filter_schemas_removes_confirm_tools(self):
        schemas = tools.schemas_for("explain", use_tools=True, surface="ask")
        names = {item["name"] for item in schemas}
        self.assertIn("save_memory", names)
        self.assertIn("run_code", names)
        kept = {item["name"] for item in evidence_gate.filter_schemas(schemas)}
        self.assertNotIn("save_memory", kept)
        self.assertNotIn("run_code", kept)
        self.assertIn("web_search", kept)
        self.assertIsNone(evidence_gate.filter_schemas(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
