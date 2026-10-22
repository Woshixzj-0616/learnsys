"""P16.1：计划 → 执行 → 自检 → 写操作确认。不连网、不用真实 key。"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import loop, planning, selfcheck, tools
from learnsys.agent.config import AgentConfig
from learnsys.agent.events import AgentEvent
from learnsys.agent.provider_anthropic import (
    ProviderEvent,
    ProviderResult,
    ToolCall,
)


def make_cfg(root: pathlib.Path) -> AgentConfig:
    return AgentConfig(
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


def tool_use(text: str, *calls: tuple[str, dict]) -> ProviderResult:
    return ProviderResult(
        text=text,
        tool_calls=[ToolCall(f"call-{index}", name, args)
                    for index, (name, args) in enumerate(calls)],
        content_blocks=(
            ([{"type": "text", "text": text}] if text else [])
            + [{"type": "tool_use", "id": f"call-{index}", "name": name, "input": args}
               for index, (name, args) in enumerate(calls)]),
        stop_reason="tool_use",
    )


class ScriptProvider:
    """按脚本逐轮返回；记录每轮收到的 tools/messages，便于断言。"""

    def __init__(self, *results: ProviderResult):
        self.results = list(results)
        self.calls = 0
        self.seen_messages: list[list] = []

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.calls += 1
        self.seen_messages.append(messages)
        result = self.results.pop(0) if self.results else ProviderResult(
            text="", stop_reason="end_turn")
        if result.text:
            yield ProviderEvent("text", result.text)
        yield ProviderEvent("done", result=result)


class TestPlanning(unittest.TestCase):
    def test_truncates_to_six_steps(self):
        raw = [{"title": f"第{i}步", "tool": "today_summary"} for i in range(10)]
        steps, truncated = planning.normalize_steps(raw)
        self.assertEqual(len(steps), planning.MAX_STEPS)
        self.assertTrue(truncated)
        self.assertEqual(steps[0]["status"], "pending")

    def test_drops_empty_titles_and_accepts_strings(self):
        steps, truncated = planning.normalize_steps(
            [{"title": "  "}, "看记录", {"title": "搜资料", "tool": "search_materials"}])
        self.assertEqual([step["title"] for step in steps], ["看记录", "搜资料"])
        self.assertFalse(truncated)

    def test_empty_plan(self):
        steps, truncated = planning.normalize_steps("不是列表")
        self.assertEqual(steps, [])
        self.assertFalse(truncated)

    def test_match_step_by_tool_and_mark_progress(self):
        steps, _ = planning.normalize_steps([
            {"title": "看错题", "tool": "recent_wrong_items"},
            {"title": "搜资料", "tool": "search_materials"},
        ])
        index = planning.match_step(steps, "search_materials")
        self.assertEqual(index, 1)
        planning.mark_step(steps, index, "failed")
        self.assertEqual(steps[1]["status"], "failed")
        self.assertIsNone(planning.match_step(steps, "search_materials"))


class TestSelfCheck(unittest.TestCase):
    def evidence(self, content: str, name: str = "search_materials",
                 args: dict | None = None) -> selfcheck.Evidence:
        evidence = selfcheck.Evidence()
        evidence.add(name, args or {}, content)
        return evidence

    def test_page_seen_in_tool_result_passes(self):
        evidence = self.evidence("【资料 3：数据结构课件 · 第 2 页】\n栈是后进先出。")
        issues = selfcheck.verify("栈是后进先出。【资料 3：数据结构课件 · 第 2 页】", evidence)
        self.assertEqual(issues, [])

    def test_fabricated_page_is_flagged(self):
        evidence = self.evidence("【资料 3：数据结构课件 · 第 2 页】\n栈是后进先出。")
        issues = selfcheck.verify("栈是后进先出。【资料 3：数据结构课件 · 第 9 页】", evidence)
        self.assertEqual(len(issues), 1)
        self.assertIn("第 9 页", issues[0])

    def test_page_list_checks_every_page(self):
        evidence = self.evidence("【资料 3：数据结构课件 · 第 2 页】")
        issues = selfcheck.verify("【资料 3：数据结构课件 · 第 1、9 页】", evidence)
        self.assertEqual(len(issues), 2)
        self.assertTrue(all("第" in issue for issue in issues))

    def test_read_material_page_range_is_known(self):
        evidence = selfcheck.Evidence()
        evidence.add("read_material", {"material_id": 4},
                     "【数据结构】共 9000 字；第 1–3 页；本次读 0–6000 字\n栈是后进先出。")
        issues = selfcheck.verify("【资料 4：数据结构 · 第 2、3 页】", evidence)
        self.assertEqual(issues, [])

    def test_fabricated_material_id_is_flagged(self):
        evidence = self.evidence("【资料 3：数据结构课件 · 第 2 页】")
        issues = selfcheck.verify("【资料 7：操作系统课件 · 第 2 页】", evidence)
        self.assertTrue(any("#7" in issue for issue in issues))

    def test_fabricated_wrong_item_id_is_flagged(self):
        evidence = self.evidence("错题 #12 ｜ 题目：进程调度", "recent_wrong_items")
        issues = selfcheck.verify("可以再看错题 #19 的变式。", evidence)
        self.assertEqual(len(issues), 1)
        self.assertIn("#19", issues[0])

    def test_claim_without_any_tool_is_flagged(self):
        issues = selfcheck.verify("根据资料里的说法，栈是先进先出。", selfcheck.Evidence())
        self.assertTrue(any("没有调用任何工具" in issue for issue in issues))

    def test_no_citation_and_no_claim_passes(self):
        self.assertEqual(selfcheck.verify("栈是后进先出。", selfcheck.Evidence()), [])


class TestPlanLoop(unittest.TestCase):
    def test_plan_event_and_step_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = ScriptProvider(
                tool_use("先列个计划。", ("make_plan", {"steps": [
                    {"title": "看今天的记录", "tool": "today_summary"},
                    {"title": "搜资料", "tool": "search_materials"},
                ]}), ("today_summary", {})),
                ProviderResult(text="今天学了这些。", stop_reason="end_turn"),
            )
            events = list(loop.run(loop.AgentRequest("我今天学了什么"),
                                   provider=fake, cfg=cfg))
            plan_events = [event for event in events if event.kind == "plan"]
            self.assertEqual(len(plan_events), 1)
            self.assertEqual(len(plan_events[0].data["steps"]), 2)
            tool_end = [event for event in events if event.kind == "tool_end"
                        and event.data.get("name") == "today_summary"][0]
            self.assertEqual(tool_end.data["step"], 0)
            self.assertEqual(tool_end.data["goal"], "看今天的记录")
            self.assertTrue(tool_end.data["ok"])
            updates = [event for event in events if event.kind == "plan_update"]
            self.assertTrue(any(item.data["index"] == 0 and item.data["status"] == "done"
                                for item in updates))
            self.assertEqual(events[-1].kind, "done")

    def test_tool_failure_is_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = ScriptProvider(
                tool_use("我读一下。", ("read_material", {"material_id": 99999})),
                ProviderResult(text="这份资料不在库里。", stop_reason="end_turn"),
            )
            events = list(loop.run(loop.AgentRequest("读第三份资料"),
                                   provider=fake, cfg=cfg))
            tool_end = [event for event in events if event.kind == "tool_end"][0]
            self.assertFalse(tool_end.data["ok"])
            self.assertTrue(tool_end.data["preview"])
            self.assertEqual(events[-1].kind, "done")


class TestWriteConfirmation(unittest.TestCase):
    def run_save_memory(self, approve):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        cfg = make_cfg(root)
        fake = ScriptProvider(
            tool_use("记一下。", ("save_memory", {"content": "回答用中文",
                                                   "kind": "rule"})),
            ProviderResult(text="记住了。", stop_reason="end_turn"),
        )
        seen = {}

        def confirm(request_id, name, args):
            seen["name"] = name
            seen["args"] = args
            return approve

        events = list(loop.run(loop.AgentRequest("记住以后都用中文"),
                               provider=fake, cfg=cfg, confirm=confirm))
        conn = store.connect(root / "learning.db")
        try:
            count = conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0]
        finally:
            conn.close()
        return events, count, seen

    def test_denied_write_is_not_executed(self):
        events, count, seen = self.run_save_memory(False)
        self.assertEqual(seen["name"], "save_memory")
        self.assertEqual(count, 0)
        confirm_events = [event for event in events if event.kind == "confirm"]
        self.assertEqual(len(confirm_events), 1)
        self.assertIn("中文", confirm_events[0].data["summary"])
        tool_end = [event for event in events if event.kind == "tool_end"][0]
        self.assertTrue(tool_end.data["denied"])
        self.assertFalse(tool_end.data["ok"])
        self.assertIn("没有写入", events[-1].data["text"])

    def test_approved_write_is_executed(self):
        events, count, _ = self.run_save_memory(True)
        self.assertEqual(count, 1)
        tool_end = [event for event in events if event.kind == "tool_end"][0]
        self.assertFalse(tool_end.data.get("denied"))
        self.assertTrue(tool_end.data["ok"])

    def test_no_confirm_channel_means_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = ScriptProvider(
                tool_use("记一下。", ("save_memory", {"content": "回答用中文"})),
                ProviderResult(text="这条需要你确认。", stop_reason="end_turn"),
            )
            events = list(loop.run(loop.AgentRequest("记住用中文"),
                                   provider=fake, cfg=cfg))
            tool_end = [event for event in events if event.kind == "tool_end"][0]
            self.assertTrue(tool_end.data["denied"])
            conn = store.connect(pathlib.Path(tmp) / "learning.db")
            try:
                count = conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 0)


class TestRewrite(unittest.TestCase):
    def test_failed_check_triggers_one_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(pathlib.Path(tmp))
            fake = ScriptProvider(
                tool_use("查一下资料。", ("search_materials", {"query": "栈"})),
                ProviderResult(text="栈是后进先出。【资料 1：数据结构 · 第 9 页】",
                               stop_reason="end_turn"),
                ProviderResult(text="栈是后进先出。【资料 1：数据结构 · 第 2 页】",
                               stop_reason="end_turn"),
            )
            raw = "【资料 1：数据结构 · 第 2 页】\n栈是后进先出。"
            with mock.patch.object(loop.tools, "execute",
                                   return_value=(raw, "搜了资料库", True)):
                events = list(loop.run(loop.AgentRequest("栈是什么"),
                                       provider=fake, cfg=cfg))
            checks = [event for event in events if event.kind == "check"]
            self.assertFalse(checks[0].data["ok"])
            self.assertTrue(any(event.kind == "rewrite" for event in events))
            self.assertTrue(checks[-1].data["ok"])
            self.assertIn("第 2 页", events[-1].data["text"])
            self.assertNotIn("第 9 页", events[-1].data["text"])
            self.assertEqual(fake.calls, 3)


class TestNewTools(unittest.TestCase):
    def test_schemas_include_plan_and_wrong_items(self):
        names = {schema["name"] for schema in tools.schemas_for("explain")}
        self.assertIn("make_plan", names)
        self.assertIn("recent_wrong_items", names)

    def test_recent_wrong_items_lists_ids_and_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cfg = make_cfg(root)
            conn = store.connect(root / "learning.db")
            try:
                material_id, _ = store.add_material(
                    conn, title="数据结构课件", body="栈是后进先出。")
                item_id, _ = store.add_wrong_item(
                    conn, question="栈和队列的区别？", answer="后进先出 vs 先进先出",
                    my_answer="栈是先进先出", material_id=material_id)
            finally:
                conn.close()
            ctx = tools.ToolContext(data_root=root, db_path=root / "learning.db")
            text, preview, ok = tools.execute("recent_wrong_items", {"limit": 5}, ctx)
            self.assertTrue(ok)
            self.assertIn(f"#{item_id}", text)
            self.assertIn("栈和队列的区别", text)
            self.assertIn("数据结构课件", text)
            self.assertEqual(preview, "读了最近的错题")

    def test_execute_returns_three_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ctx = tools.ToolContext(data_root=root)
            text, preview, ok = tools.execute("today_summary", {}, ctx)
            self.assertIsInstance(text, str)
            self.assertIsInstance(preview, str)
            self.assertTrue(ok)


class TestAgentRunsStore(unittest.TestCase):
    def test_add_and_read_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(pathlib.Path(tmp) / "learning.db")
            try:
                run_id = store.add_agent_run(
                    conn, run_id="r1", conversation_id=7, question="测试",
                    model="test-model", mode="explain", started_at="2026-10-22 10:00:00",
                    finished_at="2026-10-22 10:00:09", first_ms=800, total_ms=9000,
                    steps=2, stop_reason="end_turn",
                    usage={"input_tokens": 10, "output_tokens": 20},
                    trace=[{"kind": "plan", "data": {"steps": ["a"]}},
                           {"kind": "check", "data": {"ok": True}}],
                    check_ok=True, error="")
                row = store.get_agent_run(conn, run_id="r1")
            finally:
                conn.close()
            self.assertEqual(row["id"], run_id)
            self.assertEqual(row["conversation_id"], 7)
            self.assertEqual(row["usage"]["output_tokens"], 20)
            self.assertEqual(row["trace"][0]["kind"], "plan")
            self.assertTrue(row["check_ok"])


if __name__ == "__main__":
    unittest.main()
