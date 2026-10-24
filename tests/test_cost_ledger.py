# -*- coding: utf-8 -*-
"""按模型单价、每日上限、模型调用账本。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import agent, store
from learnsys.agent import budget
from learnsys.agent import cost as agent_cost
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult
from learnsys.server import routes_settings


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    base = AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="test-model",
        fast_model="test-fast",
        max_tokens=1024,
        thinking=False,
        vision_base_url="",
        vision_api_key="",
        vision_model="glm-4v-flash",
        data_root=root,
        profile_path=root / "学习档案.md",
    )
    return base.__class__(**{**base.__dict__, **overrides})


class UsageProvider:
    def __init__(self, usage: dict, text: str = "好"):
        self.usage = usage
        self.text = text
        self.calls = 0

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.calls += 1
        yield ProviderEvent("done", result=ProviderResult(
            text=self.text, usage=dict(self.usage), stop_reason="end_turn"))


class PriceTest(unittest.TestCase):
    def test_model_price_overrides_global(self):
        root = pathlib.Path(tempfile.gettempdir())
        cfg = make_cfg(root, price_input=1, price_output=2, price_cache_read=0.1,
                       prices={"pro": {"input": 10, "output": 20, "cache_read": 1}})
        self.assertEqual(agent_cost.price_for(cfg, "pro"), (10, 20, 1))
        self.assertEqual(agent_cost.price_for(cfg, "other"), (1, 2, 0.1))
        usage = {"input_tokens": 1000, "output_tokens": 500}
        amount, currency, note = agent_cost.estimate(usage, cfg, "pro")
        self.assertAlmostEqual(amount, 0.02, places=6)
        self.assertEqual(note, "")
        self.assertEqual(currency, "USD")

    def test_all_zero_is_unconfigured(self):
        root = pathlib.Path(tempfile.gettempdir())
        cfg = make_cfg(root, prices={"pro": {"input": 0, "output": 0}})
        amount, _, note = agent_cost.estimate(
            {"input_tokens": 1000, "output_tokens": 500}, cfg, "pro")
        self.assertEqual(amount, 0.0)
        self.assertEqual(note, "未配置单价")

    def test_estimate_by_model_sums(self):
        root = pathlib.Path(tempfile.gettempdir())
        cfg = make_cfg(root, price_input=1, price_output=1,
                       prices={"pro": {"input": 10, "output": 10}})
        by_model = {
            "flash": {"input_tokens": 1_000_000, "output_tokens": 0},
            "pro": {"input_tokens": 1_000_000, "output_tokens": 0},
        }
        amount, _, configured = agent_cost.estimate_by_model(by_model, cfg)
        self.assertTrue(configured)
        self.assertAlmostEqual(amount, 11.0, places=6)


class CleanPricesTest(unittest.TestCase):
    def test_clean_drops_empty_and_negative(self):
        cleaned = routes_settings._clean_prices({
            "pro": {"input": 1, "output": 2, "cache_read": -3},
            "": {"input": 1},
            "zero": {"input": 0, "output": 0},
            "bad": {"input": "x", "output": 4},
        })
        self.assertEqual(cleaned, {"pro": {"input": 1.0, "output": 2.0,
                                           "cache_read": 0.0},
                                   "bad": {"input": 0.0, "output": 4.0,
                                           "cache_read": 0.0}})

    def test_clean_caps_entries(self):
        raw = {f"m{i}": {"input": 1} for i in range(150)}
        self.assertEqual(len(routes_settings._clean_prices(raw)), 100)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_run_writes_ledger_with_model_price(self):
        cfg = make_cfg(self.root, model="pro", price_input=1, price_output=1,
                       prices={"pro": {"input": 10, "output": 20}})
        provider = UsageProvider({"input_tokens": 1000, "output_tokens": 500})
        events = list(agent.run(
            agent.AgentRequest(message="你好", use_tools=False),
            cfg=cfg, provider=provider))
        done = [event for event in events if event.kind == "done"][-1]
        self.assertAlmostEqual(float(done.data.get("cost") or 0), 0.02, places=6)
        self.assertIn("pro", done.data.get("usage_by_model") or {})

        conn = store.connect(self.root / "learning.db")
        try:
            totals = store.day_totals(conn)
            models = store.day_by_model(conn)
        finally:
            conn.close()
        self.assertEqual(totals["calls"], 1)
        self.assertAlmostEqual(totals["cost"], 0.02, places=6)
        self.assertEqual(models[0]["model"], "pro")
        self.assertAlmostEqual(models[0]["cost"], 0.02, places=6)


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def _seed(self, cost: float = 0.0, calls: int = 1) -> None:
        conn = store.connect(self.root / "learning.db")
        try:
            for _ in range(calls):
                store.add_model_usage(conn, source="test", model="m",
                                      counts={"total_tokens": 10},
                                      cost=cost, currency="USD")
        finally:
            conn.close()

    def test_call_limit_blocks_before_provider(self):
        self._seed(calls=2)
        cfg = make_cfg(self.root, daily_call_limit=2)
        provider = UsageProvider({"input_tokens": 10, "output_tokens": 10})
        events = list(agent.run(agent.AgentRequest(message="你好", use_tools=False),
                                cfg=cfg, provider=provider))
        self.assertEqual(provider.calls, 0)
        errors = [event.text for event in events if event.kind == "error"]
        self.assertTrue(errors)
        self.assertIn("每日调用上限", errors[0])

    def test_cost_limit_blocks(self):
        self._seed(cost=1.5)
        cfg = make_cfg(self.root, daily_cost_limit=1.0)
        provider = UsageProvider({"input_tokens": 10, "output_tokens": 10})
        events = list(agent.run(agent.AgentRequest(message="你好", use_tools=False),
                                cfg=cfg, provider=provider))
        self.assertEqual(provider.calls, 0)
        self.assertTrue(any("花费已达上限" in (event.text or "")
                            for event in events if event.kind == "error"))

    def test_no_limit_runs_normally(self):
        self._seed(calls=3)
        cfg = make_cfg(self.root)
        self.assertIsNone(budget.check(cfg))
        provider = UsageProvider({"input_tokens": 10, "output_tokens": 10})
        list(agent.run(agent.AgentRequest(message="你好", use_tools=False),
                       cfg=cfg, provider=provider))
        self.assertEqual(provider.calls, 1)


class SchemaTest(unittest.TestCase):
    def test_model_usage_table_exists(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = store.connect(pathlib.Path(tmp.name) / "learning.db")
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='model_usage'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
