"""P35.0 golden set 的静态门禁：题目完整、id 唯一、profile 不藏掉预期工具。"""
from __future__ import annotations

import json
import pathlib
import unittest

from learnsys.agent import tools

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "docs" / "golden" / "qa-golden-50.json"


class QAGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.cases = cls.data.get("cases") or []

    def test_fifty_unique_cases(self):
        self.assertEqual(len(self.cases), 50)
        ids = [item["id"] for item in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for item in self.cases:
            self.assertIn("category", item)
            self.assertTrue(item.get("question"))
            self.assertIn("expected", item)

    def test_assistant_profile_offers_expected_tools(self):
        for case in self.cases:
            expected = case.get("expected") or {}
            need = set(expected.get("tools_any") or [])
            if not need:
                continue
            message = (case.get("turns") or [case.get("question") or ""])[-1]
            names = {item["name"] for item in (
                tools.schemas_for("explain", profile="assistant",
                                  message=message) or [])}
            self.assertTrue(
                need & names,
                f"{case['id']} 需要 {sorted(need)}，但 assistant 只给了 {sorted(names)}")

    def test_removed_tools_never_in_assistant(self):
        for case in self.cases:
            message = (case.get("turns") or [case.get("question") or ""])[-1]
            names = {item["name"] for item in (
                tools.schemas_for("explain", profile="assistant",
                                  message=message) or [])}
            for removed in ("open_file", "launch_app", "open_url",
                            "browser_status", "browser_history",
                            "life_cards", "life_items", "art_works",
                            "travel_trace", "write_study_file", "delete_vocab"):
                self.assertNotIn(removed, names, case["id"])


if __name__ == "__main__":
    unittest.main()
