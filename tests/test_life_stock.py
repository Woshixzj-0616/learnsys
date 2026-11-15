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


class _FakeBytesResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _sina_line(symbol: str, name: str, price: float, pre_close: float,
               day: str = "2026-11-13") -> str:
    parts = [name, "0", str(pre_close), str(price), "0", "0"] + ["0"] * 24
    parts += [day, "15:43:57", "00"]
    return f'var hq_str_{symbol}="{",".join(parts)}";'


SINA_BODY = "\n".join([
    _sina_line("sh000001", "上证指数", 3634.3530, 3655.8295),
    _sina_line("sz399001", "深证成指", 10968.787, 11197.977),
]).encode("gbk")


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

    def test_index_uses_eastmoney(self):
        payload = {"rc": 0, "data": {"diff": [
            {"f2": 359902, "f3": -144, "f4": -5241,
             "f12": "000001", "f14": "上证指数"},
        ]}}
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(payload)) as call:
            rows = stock.fetch_index_quotes(["000001.SH"], DAY)
        url = call.call_args.args[0].full_url
        self.assertIn("secids=1.000001", url)
        self.assertEqual(rows[0]["close"], 3599.02)
        self.assertEqual(rows[0]["pct_chg"], -1.44)
        self.assertEqual(rows[0]["name"], "上证指数")

    def test_empty_items_returns_empty(self):
        payload = {"code": 0, "msg": "", "data": {"fields": [], "items": []}}
        with mock.patch.object(stock.urllib.request, "urlopen",
                               return_value=_FakeResponse(payload)):
            self.assertEqual(stock.fetch_quotes(["600519.SH"], "token", DAY), [])

    def test_index_retries_eastmoney_once(self):
        payload = {"rc": 0, "data": {"diff": [
            {"f2": 359902, "f3": -144, "f4": -5241,
             "f12": "000001", "f14": "上证指数"},
        ]}}
        calls = []

        def fake_urlopen(request, timeout=10):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise ConnectionResetError("对端断开")
            return _FakeResponse(payload)

        with mock.patch.object(stock.urllib.request, "urlopen",
                               side_effect=fake_urlopen), \
                mock.patch.object(stock, "HTTP_RETRY_SLEEP", 0):
            rows = stock.fetch_index_quotes(["000001.SH"], DAY)
        self.assertEqual(len(calls), 2)
        self.assertEqual(rows[0]["source"], "eastmoney")
        self.assertEqual(rows[0]["close"], 3599.02)

    def test_index_falls_back_to_sina(self):
        calls = []

        def fake_urlopen(request, timeout=10):
            calls.append(request.full_url)
            if "eastmoney" in request.full_url:
                raise ConnectionResetError("对端断开")
            return _FakeBytesResponse(SINA_BODY)

        with mock.patch.object(stock.urllib.request, "urlopen",
                               side_effect=fake_urlopen), \
                mock.patch.object(stock, "HTTP_RETRY_SLEEP", 0), \
                mock.patch.object(stock.diagnostics, "log_swallow"):
            rows = stock.fetch_index_quotes(["000001.SH", "399001.SZ"], DAY)
        self.assertEqual(len(calls), 3)          # 东财 2 次 + 新浪 1 次
        self.assertEqual([row["source"] for row in rows], ["sina", "sina"])
        self.assertAlmostEqual(rows[0]["close"], 3634.3530, places=4)
        self.assertAlmostEqual(rows[0]["pct_chg"], -0.5877, places=3)
        self.assertEqual(rows[0]["trade_date"], "2026-11-13")
        self.assertIn("hq.sinajs.cn", calls[-1])


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
        self.assertIn("代码", str(ctx.exception))

    def test_index_only_needs_no_token(self):
        sub = self._sub(sources=["000001.SH"])
        rows = [{"code": "000001.SH", "name": "上证指数",
                 "trade_date": DAY, "close": 3599.02, "pct_chg": -1.44,
                 "change": -52.41}]
        with mock.patch.object(stock, "configured_token", return_value=""), \
                mock.patch.object(stock, "fetch_index_quotes", return_value=rows):
            card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(card["content"]["source"], "eastmoney")
        self.assertIn("上证指数", card["content"]["summary"])
        self.assertIn("3599.02", card["content"]["summary"])

    def test_index_fallback_source_in_card(self):
        sub = self._sub(sources=["000001.SH"])
        rows = [{"code": "000001.SH", "name": "上证指数",
                 "trade_date": DAY, "close": 3634.35, "pct_chg": -0.59,
                 "change": -21.48, "source": "sina"}]
        with mock.patch.object(stock, "fetch_index_quotes", return_value=rows):
            card = cards.generate(self.conn, sub, DAY)
        self.assertEqual(card["content"]["source"], "sina")
        self.assertEqual(card["content"]["items"][0]["source"], "新浪财经")

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
