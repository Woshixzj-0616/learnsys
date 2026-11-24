"""P35.1 问答 profile：工具裁剪、短提示词、list_vocab。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys import prompt_budget, store
from learnsys.agent import loop, prompts, tools
from learnsys.agent.turn import AgentRequest
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult


class CapturingProvider:
    """不连网：记录本轮 system / tools，然后直接给一句答案。"""

    def __init__(self):
        self.system = ""
        self.tools = None

    def stream_messages(self, cfg, system, messages, tools, *,
                        abort=None, response_sink=None):
        self.system = system
        self.tools = tools
        yield ProviderEvent("done", result=ProviderResult(
            text="rsync 用滚动校验和块级比对。", stop_reason="end_turn"))


def _names(**kwargs) -> list[str]:
    schemas = tools.schemas_for("explain", **kwargs) or []
    return [item["name"] for item in schemas]


class TestQAProfileTools(unittest.TestCase):
    def test_assistant_core_is_small_and_learning_only(self):
        names = _names(profile="assistant", message="rsync 的算法是什么")
        self.assertEqual(len(names), 11)
        for expected in ("search_materials", "read_material", "search_records",
                         "recent_wrong_items", "due_reviews", "list_vocab",
                         "web_search", "fetch_url", "run_code",
                         "save_memory", "forget_memory"):
            self.assertIn(expected, names)
        for removed in ("open_file", "launch_app", "open_url", "browser_status",
                        "browser_history", "life_cards", "life_items",
                        "art_works", "travel_trace", "write_study_file",
                        "delete_vocab"):
            self.assertNotIn(removed, names)

    def test_intent_adds_only_needed_tools(self):
        self.assertIn("get_mastery", _names(profile="assistant", message="我最弱的知识点是什么"))
        self.assertIn("get_train_summary", _names(profile="assistant", message="我写作练得怎么样"))
        self.assertIn("get_cet6_context", _names(profile="assistant", message="六级精听这段怎么练"))
        self.assertIn("add_vocab", _names(profile="assistant", message="记一下这个词"))
        self.assertIn("save_wrongbook", _names(profile="assistant", message="把这题收进复习"))
        self.assertIn("make_plan", _names(profile="assistant", message="把资料和错题整理成计划"))
        self.assertNotIn("get_mastery", _names(profile="assistant", message="rsync 的算法是什么"))

    def test_quick_profile_is_lighter(self):
        names = _names(profile="assistant.quick", message="rsync 全名")
        self.assertEqual(len(names), 8)
        self.assertIn("list_vocab", names)
        self.assertNotIn("run_code", names)
        self.assertNotIn("read_material", names)

    def test_attachment_and_image_are_conditional(self):
        base = _names(profile="assistant", message="解释这段")
        self.assertNotIn("read_attachment", base)
        self.assertNotIn("ocr_image", base)
        with_attachment = _names(profile="assistant", message="解释这段",
                                 has_attachment=True)
        self.assertIn("read_attachment", with_attachment)
        with_image = _names(profile="assistant", message="解释这段", has_image=True)
        self.assertIn("ocr_image", with_image)


class TestAssistantPrompt(unittest.TestCase):
    def test_prompt_is_short_and_has_contract(self):
        system = prompts.build_system("explain", agent_profile="assistant",
                                      message="rsync 的算法是什么")
        self.assertIn("专属学习助手", system)
        self.assertIn("纠错轮", system)
        self.assertNotIn("open_file", system)
        self.assertLess(prompt_budget.estimate_tokens(system), 1600)

    def test_subject_selection(self):
        self.assertEqual(prompts.subject_for("rsync 的算法是什么"), "networks")
        self.assertEqual(prompts.subject_for("vector::emplace 报错"), "cpp")
        self.assertEqual(prompts.subject_for("分块查找的复杂度"), "algorithms")
        self.assertEqual(prompts.subject_for("年夜饭翻译"), "english")
        self.assertEqual(prompts.subject_for("今天天气"), "")


class TestAssistantLoop(unittest.TestCase):
    def test_assistant_loop_uses_short_prompt_and_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            store.connect(root / "learning.db").close()
            cfg = AgentConfig(
                base_url="http://127.0.0.1:9/v1", auth_token="test",
                model="test-model", fast_model="test-fast", max_tokens=1024,
                thinking=False, vision_base_url="", vision_api_key="",
                vision_model="", data_root=root,
                profile_path=root / "学习档案.md")
            provider = CapturingProvider()
            events = list(loop.run(
                AgentRequest(message="rsync 的算法是什么", profile="assistant"),
                cfg=cfg, provider=provider))
            self.assertIn("专属学习助手", provider.system)
            self.assertNotIn("open_file", provider.system)
            names = [item["name"] for item in (provider.tools or [])]
            self.assertEqual(len(names), 11)
            self.assertIn("list_vocab", names)
            self.assertNotIn("life_cards", names)
            self.assertEqual(events[-1].kind, "done")


class TestListVocab(unittest.TestCase):
    def test_list_vocab_reads_active_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            db = root / "learning.db"
            conn = store.connect(db)
            try:
                store.add_vocab(conn, word="emplace", meaning="原地构造",
                                source="test")
            finally:
                conn.close()
            ctx = tools.ToolContext(data_root=root, db_path=db)
            text, preview, ok = tools.execute("list_vocab", {}, ctx)
            self.assertTrue(ok)
            self.assertEqual(preview, "读了生词本")
            self.assertIn("emplace", text)
            self.assertIn("生词 #", text)
            self.assertIn("原地构造", text)

    def test_list_vocab_query_miss_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            db = root / "learning.db"
            store.connect(db).close()
            ctx = tools.ToolContext(data_root=root, db_path=db)
            text, _preview, ok = tools.execute("list_vocab", {"query": "不存在"}, ctx)
            self.assertTrue(ok)
            self.assertIn("没有匹配", text)


if __name__ == "__main__":
    unittest.main()
