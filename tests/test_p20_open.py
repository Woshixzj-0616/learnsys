# -*- coding: utf-8 -*-
"""P20.1：Agent 打开文件 / 启动程序——校验规则、确认闸门、电脑助手回归。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import loop, tools
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult, ToolCall
from learnsys.services import ops


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


def tool_use(text: str, name: str, args: dict) -> ProviderResult:
    return ProviderResult(
        text=text,
        tool_calls=[ToolCall("call-1", name, args)],
        content_blocks=[{"type": "tool_use", "id": "call-1", "name": name,
                         "input": args}],
        stop_reason="tool_use",
    )


class ScriptProvider:
    def __init__(self, *results: ProviderResult):
        self.results = list(results)
        self.seen_messages: list[list] = []

    def stream_messages(self, cfg, system, messages, tools, *, abort=None,
                        response_sink=None):
        self.seen_messages.append(messages)
        result = self.results.pop(0) if self.results else ProviderResult(
            text="", stop_reason="end_turn")
        if result.text:
            yield ProviderEvent("text", result.text)
        yield ProviderEvent("done", result=result)


class OpenFileValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_empty_path_rejected(self):
        with self.assertRaises(ValueError):
            ops.open_path("")

    def test_too_long_path_rejected(self):
        with self.assertRaises(ValueError) as caught:
            ops.open_path("D:\\" + "a" * (ops.OPEN_MAX_PATH + 1))
        self.assertIn("太长", str(caught.exception))

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError) as caught:
            ops.open_path("课件/网络.pdf")
        self.assertIn("绝对路径", str(caught.exception))

    def test_unc_path_rejected(self):
        with self.assertRaises(ValueError) as caught:
            ops.open_path(r"\\server\share\a.pdf")
        self.assertIn("网络共享", str(caught.exception))

    def test_system_dir_rejected(self):
        with self.assertRaises(ValueError) as caught:
            ops.open_path(r"C:\Windows\notepad.exe")
        self.assertIn("系统目录", str(caught.exception))

    def test_executable_suffix_rejected(self):
        victim = self.root / "危险.exe"
        victim.write_bytes(b"")
        with self.assertRaises(ValueError) as caught:
            ops.open_path(str(victim))
        self.assertIn("可执行文件", str(caught.exception))

    def test_script_suffix_rejected(self):
        victim = self.root / "脚本.ps1"
        victim.write_text("echo 1", encoding="utf-8")
        with self.assertRaises(ValueError):
            ops.open_path(str(victim))

    def test_missing_path_rejected(self):
        with self.assertRaises(ValueError) as caught:
            ops.open_path(str(self.root / "不存在.txt"))
        self.assertIn("找不到", str(caught.exception))

    def test_normal_file_opens(self):
        target = self.root / "网络.pdf"
        target.write_bytes(b"%PDF-1.4")
        with mock.patch.object(ops.os, "startfile") as startfile:
            result = ops.open_path(str(target))
        startfile.assert_called_once_with(str(target.resolve()))
        self.assertEqual(result, f"已打开文件：{target.resolve()}")

    def test_directory_opens(self):
        target = self.root / "课件"
        target.mkdir()
        with mock.patch.object(ops.os, "startfile") as startfile:
            result = ops.open_path(str(target))
        startfile.assert_called_once_with(str(target.resolve()))
        self.assertIn("文件夹", result)

    def test_agent_path_does_not_open_urls(self):
        with mock.patch.object(ops.os, "startfile") as startfile:
            with self.assertRaises(ValueError):
                ops.open_path("https://example.com")
        startfile.assert_not_called()

    def test_assistant_path_still_opens_urls(self):
        with mock.patch.object(ops.os, "startfile") as startfile:
            result = ops.open_path("https://example.com", allow_url=True)
        startfile.assert_called_once_with("https://example.com")
        self.assertIn("网址", result)


class LaunchAppTest(unittest.TestCase):
    def test_exact_and_contains_match(self):
        index = {"记事本": r"C:\Start\记事本.lnk",
                 "计算器": r"C:\Start\计算器.lnk"}
        with mock.patch.object(ops.os, "startfile") as startfile:
            self.assertEqual(ops.launch_by_name("记事本", index), "已启动程序：记事本")
            self.assertEqual(ops.launch_by_name("记事", index), "已启动程序：记事本")
        self.assertEqual(startfile.call_count, 2)

    def test_not_found_lists_candidates(self):
        index = {"记事本": r"C:\Start\记事本.lnk",
                 "计算器": r"C:\Start\计算器.lnk"}
        with mock.patch.object(ops.os, "startfile") as startfile:
            with self.assertRaises(ValueError) as caught:
                ops.launch_by_name("绘图", index)
        startfile.assert_not_called()
        self.assertIn("没找到", str(caught.exception))
        self.assertIn("候选", str(caught.exception))

    def test_empty_and_too_long_names_rejected(self):
        with self.assertRaises(ValueError):
            ops.launch_by_name("  ", {})
        with self.assertRaises(ValueError):
            ops.launch_by_name("长" * (ops.APP_NAME_MAX + 1), {})

    def test_store_apps_parse_and_launch(self):
        parsed = ops.parse_start_apps(
            "记事本|Microsoft.WindowsNotepad_8wekyb3d8bbwe!App\r\n"
            "坏行没有分隔符\r\n"
            "计算器|Microsoft.WindowsCalculator_8wekyb3d8bbwe!App\r\n")
        self.assertEqual(parsed["记事本"],
                         r"shell:AppsFolder\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App")
        self.assertIn("计算器", parsed)
        index = {"记事本": parsed["记事本"]}
        with mock.patch.object(ops.os, "startfile") as startfile:
            result = ops.launch_by_name("记事", index)
        startfile.assert_called_once_with(parsed["记事本"])
        self.assertEqual(result, "已启动程序：记事本")


class ConfirmSchemaTest(unittest.TestCase):
    def test_open_tools_need_confirmation_but_are_not_writes(self):
        self.assertIn("open_file", tools.CONFIRM_TOOLS)
        self.assertIn("launch_app", tools.CONFIRM_TOOLS)
        self.assertNotIn("open_file", tools.WRITE_TOOLS)
        self.assertNotIn("launch_app", tools.WRITE_TOOLS)

    def test_confirmation_summary_has_full_target(self):
        path = r"D:\课件\很长很长的一级目录\第二级\网络原理.pdf"
        self.assertIn(path, tools.write_summary("open_file", {"path": path}))
        self.assertIn("记事本", tools.write_summary("launch_app", {"name": "记事本"}))

    def test_schemas_skip_quiz_mode(self):
        explain = {schema["name"] for schema in tools.schemas_for("explain")}
        quiz = {schema["name"] for schema in tools.schemas_for("quiz")}
        self.assertIn("open_file", explain)
        self.assertIn("launch_app", explain)
        self.assertNotIn("open_file", quiz)
        self.assertNotIn("launch_app", quiz)

    def test_tool_descriptions_mention_confirmation(self):
        for schema in (tools.OPEN_FILE_SCHEMA, tools.LAUNCH_APP_SCHEMA):
            self.assertIn("确认", schema["description"])


class LoopConfirmTest(unittest.TestCase):
    def _run(self, approve: bool, target: pathlib.Path):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = make_cfg(pathlib.Path(tmp.name))
        fake = ScriptProvider(
            tool_use("我来打开。", "open_file", {"path": str(target)}),
            ProviderResult(text="已经处理。", stop_reason="end_turn"),
        )
        seen = {}

        def confirm(request_id, name, args):
            seen["name"] = name
            return approve

        with mock.patch.object(ops.os, "startfile") as startfile:
            events = list(loop.run(loop.AgentRequest("打开这个文件"),
                                   provider=fake, cfg=cfg, confirm=confirm))
        return events, startfile, seen

    def test_denied_does_not_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "笔记.md"
            target.write_text("x", encoding="utf-8")
            events, startfile, seen = self._run(False, target)
        startfile.assert_not_called()
        self.assertEqual(seen["name"], "open_file")
        tool_end = [event for event in events if event.kind == "tool_end"][0]
        self.assertTrue(tool_end.data["denied"])
        self.assertIn("没有执行", events[-1].data["text"])

    def test_approved_opens_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "笔记.md"
            target.write_text("x", encoding="utf-8")
            events, startfile, _ = self._run(True, target)
        startfile.assert_called_once_with(str(target.resolve()))
        tool_end = [event for event in events if event.kind == "tool_end"][0]
        self.assertTrue(tool_end.data["ok"])
        self.assertFalse(tool_end.data.get("denied"))


class AssistantRegressionTest(unittest.TestCase):
    def test_assistant_open_rejects_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = pathlib.Path(tmp) / "setup.exe"
            victim.write_bytes(b"")
            with self.assertRaises(ValueError) as caught:
                ops.execute({"op": "open", "path": str(victim)})
        self.assertIn("可执行文件", str(caught.exception))

    def test_assistant_open_rejects_unc(self):
        with self.assertRaises(ValueError) as caught:
            ops.execute({"op": "open", "path": r"\\server\share\a.pdf"})
        self.assertIn("网络共享", str(caught.exception))

    def test_assistant_launch_uses_shared_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            lnk = pathlib.Path(tmp) / "记事本.lnk"
            lnk.write_bytes(b"")
            with mock.patch.object(ops.os, "startfile") as startfile:
                result = ops.execute({"op": "launch_app", "name": "记事"},
                                     {"记事本": str(lnk)})
        startfile.assert_called_once_with(str(lnk))
        self.assertEqual(result, "已启动程序：记事本")


if __name__ == "__main__":
    unittest.main()
