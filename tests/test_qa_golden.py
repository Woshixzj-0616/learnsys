"""P35.0 golden set 的静态门禁：题目完整、id 唯一、profile 不藏掉预期工具。"""
from __future__ import annotations

import json
import pathlib
import unittest

from learnsys.agent import tools
from tools.qa_golden_report import check_behavior, check_citation

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

    def test_image_dependent_case_is_marked(self):
        # 原题公式只在截图里：标 needs_image，离线跳过；文字版保留同一考点。
        image_case = next(c for c in self.cases if c["id"] == "fact-algo-block-plus1")
        self.assertTrue(image_case.get("needs_image"))
        text_case = next(c for c in self.cases if c["id"] == "fact-algo-block-plus1-text")
        self.assertTrue(text_case["question"].startswith("分块查找里"))
        self.assertTrue({"折半", "判定树", "log"}
                        & set(text_case["expected"]["fact_groups"][1]))

    def test_manual_verdict_cases_are_documented(self):
        for item in self.cases:
            if not item.get("manual_verdict"):
                continue
            self.assertIn(item["manual_verdict"], ("通过", "未通过"))
            self.assertTrue(item.get("manual_review"), item["id"])
            self.assertTrue(item.get("notes"), item["id"])

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


class SkipReasonTest(unittest.TestCase):
    def test_needs_image_skips_without_db(self):
        from tools.qa_golden_live import case_skip_reason
        reason = case_skip_reason(None, {"needs_image": True})
        self.assertIn("截图", reason)


class BehaviorTest(unittest.TestCase):
    """负例回归集：断言「用户排除过的方向不许再出现」。"""

    def test_plain_suggestion_is_violation(self):
        bad = check_behavior(["先检查 /var/www/html 里的内容。"],
                             {"patterns": [r"(?:查看|检查|ls)[^\n。]{0,20}/var/www"]})
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["turn"], 1)
        self.assertIn("/var/www", bad[0]["sentence"])

    def test_topic_mention_alone_is_not_violation(self):
        # 只说「nginx 的 root 在 /var/www/html」不是建议，不能判违规。
        behavior = {"patterns": [r"(?:查看|检查|ls)[^\n。]{0,20}/var/www"]}
        self.assertEqual(check_behavior(["nginx 的 root 在 /var/www/html。"], behavior), [])

    def test_negated_mention_is_not_violation(self):
        for answer, pattern in (
                ("不要再检查 Docker 容器了。", r"docker[^\n。]{0,12}容器"),
                ("这台机器不是靶机，别用 Docker。", r"docker"),
                ("不存在按位或的问题。", r"按位或"),
                ("「你需要部署靶场」这条路走不通。", r"(?:部署|搭建)[^\n。]{0,10}靶场")):
            with self.subTest(answer=answer):
                self.assertEqual(
                    check_behavior([answer], {"patterns": [pattern]}), [])

    def test_from_turn_ignores_earlier_turns(self):
        behavior = {"patterns_from_turn": 2, "patterns": [r"docker"]}
        self.assertEqual(check_behavior(["先看 Docker", "这台机器不是靶机"], behavior), [])
        bad = check_behavior(["先看 Docker", "再检查 Docker"], behavior)
        self.assertEqual([item["turn"] for item in bad], [2])

    def test_markdown_backticks_are_ignored(self):
        # 模型常写「vector 没有 `emplace` 函数」，反引号不能隔断匹配。
        bad = check_behavior(
            ["vector 没有 `emplace` 函数。"],
            {"literal_patterns": [r"vector[^\n。]{0,10}没有[^\n。]{0,8}emplace\s*函数"]})
        self.assertEqual(len(bad), 1)

    def test_correct_overload_statement_is_not_violation(self):
        # 「没有 emplace(value...) 这种重载」是正确说法，不能误伤。
        behavior = {"literal_patterns": [
            r"vector[^\n。]{0,10}没有[^\n。]{0,8}(?:这个函数|emplace\s*函数)"]}
        answer = "std::vector 没有 emplace(value...) 这种只有一个元素参数的重载。"
        self.assertEqual(check_behavior([answer], behavior), [])

    def test_score_case_behavior_is_a_hard_gate(self):
        from tools.qa_golden_live import score_case
        case = {
            "id": "neg", "category": "多轮纠错",
            "expected": {
                "fact_groups": [["没有"], ["老师"]],
                "behavior": {"patterns_from_turn": 2, "patterns": [r"docker"]},
                "max_turns": 2,
            },
        }

        def turn(answer):
            return {"answer": answer, "tools": [], "model_calls": 1,
                    "cost": 0.0, "fake_urls": [], "fake_dates": []}

        ok = score_case(case, [turn("这个文件没有写，问老师要部署包。"),
                               turn("没有 Admin.jsp，问老师要原命令。")])
        self.assertEqual(ok["status"], "通过")
        bad = score_case(case, [turn("这个文件没有写，问老师要部署包。"),
                                turn("没有 Admin.jsp，可以去 Docker 里找。")])
        self.assertEqual(bad["status"], "未通过")
        self.assertEqual(bad["behavior_violations"][0]["turn"], 2)

    def test_negative_cases_are_marked(self):
        cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
        negative = {item["id"] for item in cases
                    if (item.get("expected") or {}).get("behavior")}
        self.assertTrue({"multi-siege-admin", "multi-logic-or",
                         "multi-cpp-emplace"} <= negative)
        for item in cases:
            behavior = (item.get("expected") or {}).get("behavior")
            if not behavior:
                continue
            patterns = ((behavior.get("patterns") or [])
                        + (behavior.get("literal_patterns") or []))
            self.assertTrue(patterns, item["id"])
            self.assertFalse(item.get("manual_verdict"), item["id"])


class ManualVerdictTest(unittest.TestCase):
    def test_manual_verdict_overrides_keyword_pass(self):
        from tools.qa_golden_live import score_case
        case = {
            "id": "x", "category": "多轮纠错",
            "manual_review": True, "manual_verdict": "未通过",
            "expected": {"fact_groups": [], "must_not": [],
                         "tools_any": ["web_search"], "citation": "web",
                         "max_turns": 1},
        }
        turn = {"answer": "来源：https://a.example/（读取日期：2026-11-24）",
                "tools": ["web_search"], "model_calls": 1, "cost": 0.0,
                "fake_urls": [], "fake_dates": []}
        result = score_case(case, [turn])
        self.assertEqual(result["status"], "未通过")
        self.assertEqual(result["manual_verdict"], "未通过")


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

    def test_same_host_url_suggestion_is_not_fake(self):
        from tools.qa_golden_live import fake_urls_in
        known = {"http://shemp.whoohoo.com/Admin.jsp"}
        self.assertEqual(
            fake_urls_in("试试 http://shemp.whoohoo.com:8080/Admin.jsp", known), [])
        self.assertEqual(
            fake_urls_in("见 https://fake.example/", known),
            ["https://fake.example/"])
        self.assertEqual(fake_urls_in("本机 http://127.0.0.1:8765/", known), [])


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
