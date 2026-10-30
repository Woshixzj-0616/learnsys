# -*- coding: utf-8 -*-
"""P30.4 股票订阅：代码归一、token 本地保存、Tushare 日线解析与落卡。"""
from __future__ import annotations

import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.services.life import cards, stock

DAY = "2026-10-30"


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _tushare_payload(code="600519.SH", close=1500.0):
    return {
        "code": 0, "msg": "", "data": {
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close",
                       "pre_close", "change", "pct_chg", "vol", "amount"],
            "items": [[code, "20261030", 1490.0, 1510.0, 1480.0, close,
                       1482.2, 17.8, 1.2, 1000.0, 1500000.0]],
        },
    }


class CodeTest(unittest.TestCase):
    def test_normalize_codes(self):
        self.assertEqual(stock.normalize_codes(["600519"]), ["600519.SH"])
        self.assertEqual(stock.normalize_codes(["000001"]), ["000001.SZ"])
        self.assertEqual(stock.normalize_codes(["300750"]), ["300750.SZ"])
        self.assertEqual(stock.normalize_codes(["830799"]), ["830799.BJ"])
        self.assertEqual(stock.normalize_codes(["600519.sh", "600519.SH"]),
                         ["600519.SH"])
        self.assertEqual(stock.normalize_codes(["bad", ""]), [])

    def test_caps_at_five(self):
        codes = stock.normalize_codes([f"60000{i}" for i in range(1, 9)])
        self.assertEqual(len(codes), 5)


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = pathlib.Path(self.tmp.name) / "设置.json"
        patcher = mock.patch.object(stock.config, "SETTINGS_FILE", self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: os.environ.pop("TUSHARE_TOKEN", None))

    def test_save_and_read_token(self):
        stock.save_token("abcd1234efgh")
        self.assertEqual(stock.configured_token(), "abcd1234efgh")
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["life"]["tushare_token"], "abcd1234efgh")
        self.assertEqual(stock.mask_token("abcd1234efgh"), "••••efgh")

    def test_env_token_wins(self):
        stock.save_token("file-token")
        os.environ["TUSHARE_TOKEN"] = "env-token"
        self.assertEqual(stock.configured_token(), "env-token")

    def test_empty_save_clears(self):
        stock.save_token("abcd")
        stock.save_token("")
        self.assertEqual(stock.configured_token(), "")


class FetchTest(unittest.TestCase):
    def test_parses_tushare_daily(self):
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(_tushare_payload())) as call:
            rows = stock.fetch_quotes(["600519.SH"], "token", DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600519.SH")
        self.assertEqual(rows[0]["close"], 1500.0)
        self.assertEqual(rows[0]["pct_chg"], 1.2)
        payload = json.loads(call.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["api_name"], "daily")
        self.assertEqual(payload["params"]["ts_code"], "600519.SH")

    def test_tushare_error_is_chinese(self):
        payload = {"code": 2002, "msg": "没有权限", "data": None}
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(payload)):
            with self.assertRaises(cards.LifeUnsupported) as ctx:
                stock.fetch_quotes(["600519.SH"], "token", DAY)
        self.assertIn("Tushare", str(ctx.exception))

    def test_index_uses_index_daily(self):
        payload = _tushare_payload(code="000001.SH", close=3200.0)
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(payload)) as call:
            rows = stock.fetch_quotes(["000001.SH"], "token", DAY)
        sent = json.loads(call.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["api_name"], "index_daily")
        self.assertEqual(rows[0]["close"], 3200.0)

    def test_empty_items_returns_empty(self):
        payload = {"code": 0, "msg": "", "data": {"fields": [], "items": []}}
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(payload)):
            self.assertEqual(stock.fetch_quotes(["600519.SH"], "token", DAY), [])


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def _sub(self, **overrides):
        data = {"topic": "股票行情", "kind": "stock", "cadence": "daily",
                "at_time": "09:30", "sources": ["600519.SH"], "enabled": True}
        data.update(overrides)
        return store.upsert_subscription(self.conn, **data)

    def test_generate_writes_card(self):
        sub = self._sub()
        with mock.patch.object(stock, "configured_token", return_value="token"), \
                mock.patch.object(stock, "fetch_quotes",
                                  return_value=[{"code": "600519.SH",
                                                 "trade_date": "20261030",
                                                 "close": 1500.0, "pct_chg": 1.2,
                                                 "change": 17.8}]):
            card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(card["content"]["kind"], "stock")
        self.assertIn("600519.SH", card["content"]["summary"])
        self.assertIn("1500.00", card["content"]["summary"])
        self.assertIn("+1.20%", card["content"]["summary"])
        self.assertEqual(card["content"]["source"], "tushare")

    def test_missing_token_is_unsupported(self):
        sub = self._sub()
        with mock.patch.object(stock, "configured_token", return_value=""):
            with self.assertRaises(cards.LifeUnsupported) as ctx:
                cards.generate(self.conn, sub, DAY)
        self.assertIn("Tushare", str(ctx.exception))

    def test_missing_codes_is_unsupported(self):
        sub = self._sub(sources=[])
        with mock.patch.object(stock, "configured_token", return_value="token"):
            with self.assertRaises(cards.LifeUnsupported) as ctx:
                cards.generate(self.conn, sub, DAY)
        self.assertIn("股票代码", str(ctx.exception))

    def test_same_day_reuses_card(self):
        sub = self._sub()
        rows = [{"code": "600519.SH", "trade_date": "20261030",
                 "close": 1500.0, "pct_chg": 1.2, "change": 17.8}]
        with mock.patch.object(stock, "configured_token", return_value="token"), \
                mock.patch.object(stock, "fetch_quotes", return_value=rows):
            first = cards.generate(self.conn, sub, DAY)
            second = cards.generate(self.conn, sub, DAY)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(store.list_cards(self.conn, day=DAY)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
