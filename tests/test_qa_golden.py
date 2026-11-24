"""P35.0 golden set 的静态门禁：题目完整、id 唯一、profile 不藏掉预期工具。"""
from __future__ import annotations

import json
import pathlib
import unittest

from learnsys.agent import tools
from tools.qa_golden_report import check_citation

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "docs" / "golden" / "qa-golden-50.json"


class QAGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.cases = cls.data.get("cases") or []

    def test_unique_and_complete_cases(self):
        # 基线是 50 条；P35 收尾补了网页引用用例，只增不减。
        self.assertGreaterEqual(len(self.cases), 50)
        ids = [item["id"] for item in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for item in self.cases:
            self.assertIn("category", item)
            self.assertTrue(item.get("question"))
            self.assertIn("expected", item)

    def test_web_citation_cases_exist(self):
        # 施工单 §12：必须有用例证明「网页类回答带 URL + 日期」。
        web = [item for item in self.cases
               if (item.get("expected") or {}).get("citation") == "web"]
        self.assertGreaterEqual(len(web), 2)
        for item in web:
            expected = item["expected"]
            self.assertTrue(
                {"web_search", "fetch_url"} & set(expected.get("tools_any") or []),
                f"{item['id']} 是网页题，必须要求联网工具")
            # 不锁具体版本号：时效题的事实会过期，靠人工复核。
            self.assertEqual(expected.get("fact_groups") or [], [], item["id"])

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


class LiveScoreTest(unittest.TestCase):
    """在线 harness 的判定：网页题必须有 URL + 日期，且伪造引用一律不通过。"""

    def setUp(self):
        from tools.qa_golden_live import score_case
        self.score_case = score_case
        self.case = {
            "id": "web-x", "category": "网页时效",
            "expected": {"fact_groups": [], "must_not": [],
                         "tools_any": ["web_search"], "citation": "web",
                         "max_turns": 1},
        }

    def turn(self, answer, fake_urls=(), fake_dates=()):
        return {"answer": answer, "tools": ["web_search"], "model_calls": 1,
                "cost": 0.0, "fake_urls": list(fake_urls),
                "fake_dates": list(fake_dates)}

    def test_clean_web_answer_passes(self):
        result = self.score_case(self.case, [self.turn(
            "来源：https://www.python.org/downloads/（读取日期：2026-11-24）")])
        self.assertEqual(result["status"], "通过")

    def test_fake_url_fails(self):
        result = self.score_case(self.case, [self.turn(
            "来源：https://fake.example/（读取日期：2026-11-24）",
            fake_urls=["https://fake.example/"])])
        self.assertEqual(result["status"], "未通过")
        self.assertEqual(result["fake_urls"], ["https://fake.example/"])

    def test_missing_date_fails_citation(self):
        result = self.score_case(self.case, [self.turn(
            "来源：https://www.python.org/downloads/")])
        self.assertFalse(result["citation_ok"])
        self.assertEqual(result["status"], "未通过")


class CitationTest(unittest.TestCase):
    def test_material_citation_accepts_id_or_page(self):
        self.assertTrue(check_citation("【资料 12：TCP · 第 3 页】讲了握手", "material"))
        self.assertTrue(check_citation("见《计算机网络》第 42 页", "material"))

    def test_material_citation_accepts_explicit_not_found(self):
        # 施工单要求：没找到时明确说「资料里没有」也算守住引用口径。
        self.assertTrue(check_citation("资料库里没有找到任何相关内容。", "material"))
        self.assertTrue(check_citation("资料里没有，本地也没查到。", "material"))

    def test_material_citation_rejects_bare_answer(self):
        self.assertFalse(check_citation("rsync 是增量同步工具。", "material"))

    def test_web_citation_requires_url_and_date(self):
        self.assertFalse(check_citation("查了一下，是最新版。", "web"))
        self.assertFalse(check_citation(
            "见 https://www.python.org/downloads/ 。", "web"))
        self.assertTrue(check_citation(
            "见 https://www.python.org/downloads/ （读取日期：2026-11-24）。", "web"))
        self.assertTrue(check_citation(
            "来源 https://sqlite.org/download.html 2026-11-24 读取。", "web"))

    def test_web_citation_ignores_unrelated_dates(self):
        # 离链接很远的正文日期不能冒充网页读取日期。
        text = ("2025-12-13 真题考过这个知识点，"
                + "（此处省略无关正文）" * 6
                + "链接：https://example.com/a")
        self.assertFalse(check_citation(text, "web"))


if __name__ == "__main__":
    unittest.main()
