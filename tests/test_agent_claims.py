# -*- coding: utf-8 -*-
"""取证审核：答案 vs 证据台账的规则检查（不改写、不调模型）。"""
from __future__ import annotations

import unittest

from learnsys.agent import claims
from learnsys.agent.selfcheck import Evidence


def evidence_with(*items) -> Evidence:
    evidence = Evidence()
    for name, content in items:
        evidence.add(name, {}, content)
    return evidence


def kinds(issues) -> list[str]:
    return [issue.kind for issue in issues]


class AuditGateTest(unittest.TestCase):
    def test_plain_question_not_audited(self):
        issues = claims.audit("根因就是 X。", Evidence(),
                              "什么是死锁？", ops=False, code_debug=False)
        self.assertEqual(issues, [])

    def test_code_debug_runs(self):
        issues = claims.audit("参考 https://fake.example/a 。", Evidence(),
                              "这段代码报错", ops=False, code_debug=True)
        self.assertIn("fake_url", kinds(issues))


class FakeUrlTest(unittest.TestCase):
    def test_unknown_url_flagged(self):
        issues = claims.audit(
            "参考 https://nginx.org/en/docs/ngx_core_module.html 。",
            Evidence(), "nginx 配置问题", ops=True)
        self.assertIn("fake_url", kinds(issues))

    def test_evidence_url_ok(self):
        evidence = evidence_with(
            ("web_search", "官方文档 https://nginx.org/en/docs/ngx_core_module.html"))
        issues = claims.audit(
            "参考 https://nginx.org/en/docs/ngx_core_module.html 。",
            evidence, "nginx 配置问题", ops=True)
        self.assertNotIn("fake_url", kinds(issues))

    def test_user_supplied_url_ok(self):
        issues = claims.audit(
            "这个链接 https://example.com/a 说的对。", Evidence(),
            "看看 https://example.com/a 这个", ops=True)
        self.assertNotIn("fake_url", kinds(issues))

    def test_localhost_is_not_a_url_claim(self):
        issues = claims.audit(
            "先访问 http://localhost:8080 看看。", Evidence(),
            "nginx 配置问题", ops=True)
        self.assertNotIn("fake_url", kinds(issues))

    def test_fullwidth_note_after_url_does_not_break_match(self):
        url = "https://nginx.org/en/docs/http/server_names.html"
        evidence = evidence_with(("fetch_url", "原文：https://nginx.org/en/docs/"
                                  "http/server_names.html 正文…"))
        issues = claims.audit(f"来源：{url}（2026-10）。", evidence,
                              "server_name 写法", ops=True)
        self.assertNotIn("fake_url", kinds(issues))

    def test_placeholder_url_is_ignored(self):
        issues = claims.audit(
            "浏览器访问 `http://IP:端口/路径` 看看。", Evidence(),
            "nginx 配置问题", ops=True)
        self.assertNotIn("fake_url", kinds(issues))


class AbsoluteClaimTest(unittest.TestCase):
    def test_absolute_without_evidence_flagged(self):
        issues = claims.audit("根因就是默认站点截走了请求。", Evidence(),
                              "nginx 配置问题", ops=True)
        self.assertIn("unsupported_absolute", kinds(issues))

    def test_absolute_with_evidence_ok(self):
        evidence = evidence_with(("nginx -T", "default_server ..."))
        issues = claims.audit("根因就是默认站点截走了请求。", evidence,
                              "nginx 配置问题", ops=True)
        self.assertNotIn("unsupported_absolute", kinds(issues))


class MissingLabelTest(unittest.TestCase):
    def test_default_claim_without_label_flagged(self):
        issues = claims.audit("nginx 的默认端口是 80。", Evidence(),
                              "nginx 配置问题", ops=True)
        self.assertIn("missing_label", kinds(issues))

    def test_default_claim_with_label_ok(self):
        issues = claims.audit("nginx 的默认端口是 80（凭记忆，未验证）。",
                              Evidence(), "nginx 配置问题", ops=True)
        self.assertNotIn("missing_label", kinds(issues))

    def test_user_supplied_number_ok(self):
        issues = claims.audit("nginx 默认端口是 8080。", Evidence(),
                              "我的 8080 配置如下", ops=True)
        self.assertNotIn("missing_label", kinds(issues))

    def test_mechanism_digit_is_not_a_default_claim(self):
        answer = "默认站点的关键是 `listen 80 default_server;`，server_name 只是辅助。"
        issues = claims.audit(answer, Evidence(), "nginx 配置问题", ops=True)
        self.assertNotIn("missing_label", kinds(issues))

    def test_version_claim_flagged(self):
        issues = claims.audit("nginx 1.18 版本默认不支持这个指令。", Evidence(),
                              "nginx 配置问题", ops=True)
        self.assertIn("missing_label", kinds(issues))


class FakeOutputTest(unittest.TestCase):
    def test_fake_output_flagged(self):
        answer = "运行结果如下：\n```\ntotal 32\ndrwxr-xr-x\n```"
        issues = claims.audit(answer, Evidence(), "帮我运行 ls", ops=True)
        self.assertIn("fake_output", kinds(issues))

    def test_run_code_evidence_ok(self):
        evidence = evidence_with(("run_code", "total 32\ndrwxr-xr-x"))
        answer = "运行结果如下：\n```\ntotal 32\ndrwxr-xr-x\n```"
        issues = claims.audit(answer, evidence, "跑一下这段代码", ops=True)
        self.assertNotIn("fake_output", kinds(issues))

    def test_sample_output_ok(self):
        answer = "示例输出如下（没有实际运行）：\n```\nhello\n```"
        issues = claims.audit(answer, Evidence(), "这个问题怎么解", ops=True)
        self.assertNotIn("fake_output", kinds(issues))

    def test_exit_code_advice_is_not_fake_output(self):
        answer = ("重点看退出码和它后面跟着的日志；按这个顺序查：\n"
                  "```\nsystemctl status 服务名\njournalctl -u 服务名 -n 100\n```")
        issues = claims.audit(answer, Evidence(), "服务启动失败", ops=True)
        self.assertNotIn("fake_output", kinds(issues))

    def test_output_label_for_commands_is_not_fake_output(self):
        answer = "先看输出：\n```\ncurl -s http://127.0.0.1/ | head -5\n```"
        issues = claims.audit(answer, Evidence(), "nginx 配置问题", ops=True)
        self.assertNotIn("fake_output", kinds(issues))

    def test_reference_phrase_is_not_fake_output(self):
        answer = ("实际输出以 `status=` 为准。先跑：\n"
                  "```\nsystemctl status nginx\n```")
        issues = claims.audit(answer, Evidence(), "服务启动失败", ops=True)
        self.assertNotIn("fake_output", kinds(issues))


class DocWithoutUrlTest(unittest.TestCase):
    def test_doc_claim_without_url_flagged(self):
        issues = claims.audit("官方文档说 server_name 不能写 IP。", Evidence(),
                              "nginx 配置问题", ops=True)
        self.assertIn("doc_without_url", kinds(issues))

    def test_doc_claim_with_evidence_url_ok(self):
        evidence = evidence_with(
            ("web_search", "https://nginx.org/en/docs/http/server_names.html"))
        issues = claims.audit("官方文档里 server_name 可以写 IP。", evidence,
                              "nginx 配置问题", ops=True)
        self.assertNotIn("doc_without_url", kinds(issues))


class IssueShapeTest(unittest.TestCase):
    def test_capped_at_five_and_deduped(self):
        answer = ("根因就是 X，官方文档说 https://fake.example/a 和 "
                  "https://fake.example/b 。运行结果如下：\n```\nx\n```\n"
                  "默认端口是 80。")
        issues = claims.audit(answer, Evidence(), "nginx 配置问题", ops=True)
        self.assertLessEqual(len(issues), 5)
        self.assertEqual(len(kinds(issues)), len(set(kinds(issues))))
        for issue in issues:
            self.assertTrue(claims.issue_text(issue))

    def test_issue_text_format(self):
        issue = claims.Issue("unsupported_absolute", "没有证据就断言根因",
                             quote="根因就是")
        text = claims.issue_text(issue)
        self.assertIn("unsupported_absolute", text)
        self.assertIn("根因就是", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
