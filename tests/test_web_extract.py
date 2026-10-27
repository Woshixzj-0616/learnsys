# -*- coding: utf-8 -*-
"""网页正文抽取：隐藏节点、article 优先、数字保留回退。"""
from __future__ import annotations

import unittest

from learnsys.services.web import extract


class ExtractTest(unittest.TestCase):
    def test_drops_hidden_nodes(self):
        html = ('<html><body><p>正常</p>'
                '<p style="display:none">藏起来一</p>'
                '<p style="visibility: hidden">藏起来二</p>'
                '<p style="color:#fff;background:#ffffff">藏起来三</p>'
                '<p style="font-size:0px">藏起来四</p>'
                '<p>结尾</p></body></html>')
        text = extract.extract_text(html)
        self.assertIn("正常", text)
        self.assertIn("结尾", text)
        for hidden in ("藏起来一", "藏起来二", "藏起来三", "藏起来四"):
            self.assertNotIn(hidden, text)

    def test_prefers_article_and_keeps_numbers(self):
        body = "这里是正文。" * 200
        html = ('<html><body><nav>导航链接</nav>'
                '<article><p>' + body + '</p>'
                '<p>门票 60 元/人，电话 010-12345678。</p></article>'
                '<footer>页脚版权</footer></body></html>')
        text = extract.extract_text(html)
        self.assertIn("门票 60 元/人", text)
        self.assertIn("010-12345678", text)
        self.assertNotIn("导航链接", text)
        self.assertNotIn("页脚版权", text)

    def test_falls_back_when_main_loses_numbers(self):
        body = "普通叙述内容。" * 200
        html = ('<html><body><article><p>' + body + '</p></article>'
                '<table><tr><td>客服电话 400-123-4567</td></tr></table></body></html>')
        text = extract.extract_text(html)
        self.assertIn("400-123-4567", text)

    def test_title_and_text_of(self):
        self.assertEqual(extract.title_of("<title> 一个 &amp; 标题 </title>"), "一个 & 标题")
        self.assertEqual(extract.text_of("<b>标题</b>\n <i>摘要</i>"), "标题 摘要")

    def test_empty_input(self):
        self.assertEqual(extract.extract_text(""), "")
        self.assertEqual(extract.title_of(""), "")

    def test_clip_text(self):
        text = "字" * 300
        clipped = extract.clip_text(text, 200)
        self.assertTrue(clipped.startswith("字" * 200))
        self.assertIn("原文共 300 字", clipped)


if __name__ == "__main__":
    unittest.main()
