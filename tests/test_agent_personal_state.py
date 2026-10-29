# -*- coding: utf-8 -*-
"""P27.1 Agent 状态注入：上限、固定标题、数据流不制造 agent→services 依赖。"""
from __future__ import annotations

import ast
import pathlib
import unittest

from learnsys import context
from learnsys.agent import prompts
from learnsys.agent.turn import AgentRequest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEADING = "【个人状态（本轮自动带入，不用再调工具核对）】"


class TestClipPersonalState(unittest.TestCase):
    def test_cap_is_600(self):
        self.assertEqual(context.MAX_PERSONAL_STATE, 600)

    def test_short_text_unchanged(self):
        self.assertEqual(context.clip_personal_state("学习：今日 1/3"),
                         "学习：今日 1/3")

    def test_long_text_clipped_with_ellipsis(self):
        text = context.clip_personal_state("长" * 700)
        self.assertEqual(len(text), context.MAX_PERSONAL_STATE)
        self.assertTrue(text.endswith("…"))

    def test_none_and_whitespace(self):
        self.assertEqual(context.clip_personal_state(None), "")
        self.assertEqual(context.clip_personal_state("  \n "), "")


class TestPromptInjection(unittest.TestCase):
    def test_heading_and_body_injected(self):
        system = prompts.build_system("explain", personal_state="学习：今日 1/3")
        self.assertIn(HEADING, system)
        self.assertIn("学习：今日 1/3", system)

    def test_no_heading_without_state(self):
        self.assertNotIn(HEADING, prompts.build_system("explain"))
        self.assertNotIn(HEADING, prompts.build_system("explain", personal_state="  "))

    def test_injected_block_never_exceeds_cap(self):
        system = prompts.build_system("explain", personal_state="长" * 700)
        body = system.split(HEADING, 1)[1].strip()
        self.assertLessEqual(len(body), context.MAX_PERSONAL_STATE)
        self.assertTrue(body.endswith("…"))


class TestRequestAndWiring(unittest.TestCase):
    def test_request_has_personal_state_default(self):
        request = AgentRequest(message="今天该先做什么")
        self.assertEqual(request.personal_state, "")

    def test_loop_passes_state_to_prompt(self):
        source = (ROOT / "learnsys" / "agent" / "loop.py").read_text(
            encoding="utf-8")
        self.assertIn("personal_state=request.personal_state", source)

    def test_chat_builds_state_from_home_service(self):
        source = (ROOT / "learnsys" / "server" / "routes_agent" / "chat.py") \
            .read_text(encoding="utf-8")
        self.assertIn("home_service.agent_state", source)
        self.assertIn("personal_state=", source)

    def test_state_path_does_not_import_services(self):
        """个人状态这条链（turn → loop → prompts）只收字符串，不得摸 services。

        agent 的工具模块另有既有依赖（records/ops 等），不在 P27.1 的改造范围；
        这里锁的是本次新增的数据流，避免「agent 自己再去查一遍」。
        """
        bad: list[str] = []
        for name in ("turn.py", "loop.py", "prompts.py"):
            path = ROOT / "learnsys" / "agent" / name
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                    modules += [alias.name for alias in node.names]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                for module in modules:
                    if module == "services" or module.startswith("services.") \
                            or module == "learnsys.services" \
                            or module.startswith("learnsys.services."):
                        bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {module}")
        self.assertEqual(bad, [], f"个人状态链不得导入 services（数据流放错层）：{bad}")

    def test_no_agent_module_imports_home_service(self):
        bad: list[str] = []
        for path in (ROOT / "learnsys" / "agent").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "learnsys.services.home" in source or "services import home" in source:
                bad.append(str(path.relative_to(ROOT)))
        self.assertEqual(bad, [], f"agent 包不得自己装配个人状态：{bad}")


if __name__ == "__main__":
    unittest.main()
