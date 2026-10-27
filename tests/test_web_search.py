# -*- coding: utf-8 -*-
"""联网搜索：解析、去重、同域上限、降级、缓存。"""
from __future__ import annotations

import unittest
from unittest import mock

from learnsys.services.web import search


class SearchTest(unittest.TestCase):
    def setUp(self):
        search._CACHE.clear()

    def tearDown(self):
        search._CACHE.clear()

    def test_dedupe_and_domain_cap(self):
        hits = [
            {"title": "a", "url": "https://a.com/1", "snippet": "", "engine": "x"},
            {"title": "a2", "url": "https://a.com/1/#frag", "snippet": "", "engine": "x"},
            {"title": "b", "url": "https://a.com/2", "snippet": "", "engine": "x"},
            {"title": "c", "url": "https://a.com/3", "snippet": "", "engine": "x"},
            {"title": "d", "url": "https://b.com/1", "snippet": "", "engine": "x"},
        ]
        out = search._dedupe(hits, 10)
        urls = [hit["url"] for hit in out]
        self.assertEqual(urls.count("https://a.com/1"), 1)
        self.assertEqual(len([u for u in urls if "a.com" in u]), 2)
        self.assertIn("https://b.com/1", urls)

    def test_usable_filters_binary_and_private(self):
        self.assertFalse(search._usable("https://x.com/a.pdf"))
        self.assertFalse(search._usable("http://127.0.0.1/a"))
        self.assertFalse(search._usable("ftp://x.com/a"))
        self.assertTrue(search._usable("https://x.com/a.html"))

    def test_bing_parsing_and_unwrap(self):
        import base64
        target = "https://example.com/real"
        token = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        page = (
            '<ol><li class="b_algo"><h2><a href="https://cn.bing.com/ck/a?u=a1'
            + token + '">标题一</a></h2><p>摘要一</p></li>'
            '<li class="b_algo"><h2><a href="https://other.com/x">标题二</a></h2>'
            '<p>摘要二</p></li></ol>')
        with mock.patch.object(search.fetch, "get_raw",
                               return_value=(page.encode(), "text/html", "utf-8", "https://cn.bing.com/")):
            hits = search._bing("测试", 5)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["url"], target)
        self.assertEqual(hits[0]["title"], "标题一")
        self.assertEqual(hits[1]["url"], "https://other.com/x")

    def test_falls_back_to_bing_when_deepseek_empty(self):
        with mock.patch.object(search, "_deepseek", return_value=[]), \
                mock.patch.object(search, "_bing", return_value=[
                    {"title": "b", "url": "https://b.com/1", "snippet": "",
                     "date": "", "engine": "bing"}]):
            data = search.web_search("问题", 3)
        self.assertEqual(data["source"], "bing")
        self.assertEqual(len(data["results"]), 1)

    def test_cache(self):
        hit = {"title": "a", "url": "https://a.com/1", "snippet": "",
               "date": "", "engine": "deepseek"}
        with mock.patch.object(search, "_deepseek", return_value=[hit]) as deepseek:
            first = search.web_search("问题", 3)
            second = search.web_search("问题", 3)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(deepseek.call_count, 1)

    def test_empty_input(self):
        data = search.web_search("", 3)
        self.assertEqual(data["results"], [])
        self.assertEqual(data["source"], "none")


if __name__ == "__main__":
    unittest.main()
