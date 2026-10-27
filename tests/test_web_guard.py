# -*- coding: utf-8 -*-
"""出网安检：本机 / 内网 / 元数据 / 全角 / 端口 / 协议。"""
from __future__ import annotations

import unittest

from learnsys.services.web import guard


class GuardTest(unittest.TestCase):
    def test_blocks_local_and_private(self):
        cases = [
            "http://127.0.0.1:8765/api/health",
            "http://localhost/",
            "http://localhost:8080/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.100.100.200/",
            "http://[::1]/",
            "http://[fe80::1]/",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertNotEqual(guard.blocked_reason(url), "")

    def test_blocks_unicode_hostnames(self):
        for url in ("http://１２７.０.０.１/", "http://localhost。/",
                    "http://metadata.google.internal/"):
            with self.subTest(url=url):
                self.assertNotEqual(guard.blocked_reason(url), "")

    def test_blocks_protocol_and_port(self):
        self.assertIn("http / https", guard.blocked_reason("ftp://example.com/a"))
        self.assertIn("80 / 443", guard.blocked_reason("http://example.com:8080/"))
        self.assertIn("80 / 443", guard.blocked_reason("https://example.com:8443/"))
        self.assertIn("账号密码", guard.blocked_reason("http://user:pass@example.com/"))

    def test_allows_public_pages(self):
        for url in ("https://docs.python.org/3/", "http://example.com/a",
                    "https://api.deepseek.com/v1/tools/search"):
            with self.subTest(url=url):
                self.assertEqual(guard.blocked_reason(url), "")

    def test_check_raises(self):
        with self.assertRaises(guard.Blocked):
            guard.check("http://127.0.0.1/")
        self.assertEqual(guard.check("https://example.com/"), "https://example.com/")

    def test_ip_blocked_mapped_v6(self):
        self.assertTrue(guard.ip_blocked("::ffff:127.0.0.1"))
        self.assertFalse(guard.ip_blocked("8.8.8.8"))
        self.assertFalse(guard.ip_blocked("example.com"))


if __name__ == "__main__":
    unittest.main()
