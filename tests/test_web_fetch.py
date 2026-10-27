# -*- coding: utf-8 -*-
"""抓取层：读取上限、内容类型、兜底、内网拦截。"""
from __future__ import annotations

import unittest
from unittest import mock

from learnsys.services.web import fetch, guard


class _Headers:
    def __init__(self, ctype="text/html", charset="utf-8", encoding=""):
        self.ctype = ctype
        self.charset = charset
        self.encoding = encoding

    def get_content_type(self):
        return self.ctype

    def get_content_charset(self):
        return self.charset

    def get(self, key):
        return self.encoding if key == "content-encoding" else ""


class _Resp:
    def __init__(self, chunks, headers=None):
        self.chunks = list(chunks)
        self.headers = headers or _Headers()

    def read1(self, _n):
        return self.chunks.pop(0) if self.chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return "https://example.com/final"


class FetchTest(unittest.TestCase):
    def test_read_bounded_ok(self):
        resp = _Resp([b"abc", b"def"])
        self.assertEqual(fetch._read_bounded(resp), b"abcdef")

    def test_read_bounded_too_large(self):
        resp = _Resp([b"x" * 8, b"x" * 8])
        with mock.patch.object(fetch, "MAX_BYTES", 10):
            with self.assertRaises(fetch.FetchError):
                fetch._read_bounded(resp)

    def test_rejects_non_text_content_type(self):
        resp = _Resp([b"abc"], _Headers(ctype="image/png"))
        with mock.patch.object(fetch._OPENER, "open", return_value=resp):
            with self.assertRaises(fetch.FetchError) as ctx:
                fetch.get_raw("https://example.com/a.png")
        self.assertIn("不是网页", str(ctx.exception))

    def test_blocked_before_request(self):
        with mock.patch.object(fetch._OPENER, "open") as opened:
            with self.assertRaises(guard.Blocked):
                fetch.get_raw("http://127.0.0.1:8765/api/health")
        opened.assert_not_called()

    def test_falls_back_to_deepseek_when_direct_fails(self):
        with mock.patch.object(fetch, "get_raw", side_effect=OSError("连不上")), \
                mock.patch.object(fetch, "_deepseek_fetch", return_value="兜底正文" * 60):
            page = fetch.fetch("https://example.com/a", 2000)
        self.assertEqual(page["via"], "deepseek")
        self.assertIn("兜底正文", page["text"])

    def test_direct_fetch_extracts_text(self):
        html = "<html><title>题目</title><body><p>" + "正文" * 400 + "</p></body></html>"
        fake = _Resp([html.encode()])
        with mock.patch.object(fetch._OPENER, "open", return_value=fake):
            page = fetch.fetch("https://example.com/a", 1000)
        self.assertEqual(page["title"], "题目")
        self.assertEqual(page["via"], "direct")
        self.assertIn("正文", page["text"])

    def test_empty_body_raises(self):
        with mock.patch.object(fetch, "get_raw", side_effect=OSError("空")), \
                mock.patch.object(fetch, "_deepseek_fetch", return_value=""):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch("https://example.com/a")


if __name__ == "__main__":
    unittest.main()
