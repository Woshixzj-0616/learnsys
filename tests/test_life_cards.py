# -*- coding: utf-8 -*-
"""P30.1 订阅卡片生成：news 只过滤简报、word/custom 单轮模型、同日不重复。"""
from __future__ import annotations

import unittest
from unittest import mock

from learnsys import store
from learnsys.services.life import cards

DAY = "2026-10-30"


def _seed_briefing(conn, day=DAY, status="ready"):
    briefing_id, _ = store.create_briefing_day(conn, day)
    store.save_briefing_items(conn, briefing_id, [
        {"category": "ai", "title": "大模型发布新版本", "summary": "推理能力提升",
         "url": "https://example.com/a", "url_key": "a", "source": "量子位"},
        {"category": "hardware", "title": "新一代芯片量产", "summary": "制程进步",
         "url": "https://example.com/b", "url_key": "b", "source": "IT之家"},
    ])
    store.finish_briefing(conn, briefing_id, status=status, item_count=2)
    return briefing_id


class LifeCardsTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def _sub(self, **overrides):
        data = {"topic": "AI", "kind": "news", "cadence": "daily",
                "at_time": "07:30", "sources": [], "enabled": True}
        data.update(overrides)
        return store.upsert_subscription(self.conn, **data)

    # ------------------------------------------------------------- news
    def test_news_filters_briefing_by_topic(self):
        _seed_briefing(self.conn)
        sub = self._sub(topic="AI")
        card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(card["day"], DAY)
        self.assertEqual(card["domain"], "life")
        self.assertEqual(card["title"], "AI")
        content = card["content"]
        self.assertEqual(content["kind"], "news")
        self.assertEqual(len(content["items"]), 1)
        self.assertIn("大模型", content["items"][0]["title"])
        self.assertEqual(content["prompt_version"], cards.PROMPT_VERSION)

    def test_news_sources_filter(self):
        _seed_briefing(self.conn)
        sub = self._sub(topic="新闻", sources=["IT之家"])
        card = cards.generate(self.conn, sub, DAY)
        self.assertEqual([item["source"] for item in card["content"]["items"]],
                         ["IT之家"])

    def test_news_before_briefing_is_not_ready(self):
        sub = self._sub(topic="AI")
        with self.assertRaises(cards.LifeNotReady):
            cards.generate(self.conn, sub, DAY)
        self.assertEqual(store.list_cards(self.conn, day=DAY), [])

    def test_news_without_match_still_writes_honest_card(self):
        _seed_briefing(self.conn)
        sub = self._sub(topic="量子计算")
        card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(card["content"]["items"], [])
        self.assertIn("没有", card["content"]["summary"])

    def test_same_day_generation_reuses_one_card(self):
        _seed_briefing(self.conn)
        sub = self._sub(topic="AI")
        first = cards.generate(self.conn, sub, DAY)
        second = cards.generate(self.conn, sub, DAY)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(store.list_cards(self.conn, day=DAY)), 1)

    # ------------------------------------------------------ word / custom
    def test_custom_uses_one_model_call(self):
        sub = self._sub(topic="每天一句英语", kind="custom")
        with mock.patch.object(cards.agent, "complete",
                               return_value=("今日一句：Stay hungry.", "", {})) as call:
            card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(call.call_count, 1)
        self.assertIn("每天一句英语", call.call_args.args[0])
        self.assertEqual(card["content"]["kind"], "custom")
        self.assertIn("Stay hungry", card["content"]["summary"])
        self.assertEqual(card["content"]["items"], [])

    def test_custom_model_error_does_not_write_card(self):
        sub = self._sub(topic="今日天气", kind="custom")
        with mock.patch.object(cards.agent, "complete",
                               return_value=("", "连接超时", {})):
            with self.assertRaises(ValueError):
                cards.generate(self.conn, sub, DAY)
        self.assertEqual(store.list_cards(self.conn, day=DAY), [])

    def test_word_keeps_long_text_bounded(self):
        sub = self._sub(topic="每日一词", kind="word")
        long_text = "词" * 2000
        with mock.patch.object(cards.agent, "complete",
                               return_value=(long_text, "", {})):
            card = cards.generate(self.conn, sub, DAY)
        self.assertLessEqual(len(card["content"]["summary"]), cards.MAX_TEXT)

    # ---------------------------------------------------------- 不支持类型
    def test_price_and_stock_are_unsupported(self):
        for kind in ("price", "stock"):
            sub = self._sub(topic=f"{kind}测试", kind=kind)
            with self.assertRaises(cards.LifeUnsupported):
                cards.generate(self.conn, sub, DAY)

    def test_supported_kinds(self):
        self.assertTrue(cards.supported("news"))
        self.assertTrue(cards.supported("word"))
        self.assertTrue(cards.supported("custom"))
        self.assertFalse(cards.supported("price"))
        self.assertFalse(cards.supported("stock"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
