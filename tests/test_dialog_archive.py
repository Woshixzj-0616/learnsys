"""对话总汇：脱敏、围栏、来源过滤、封存与校验。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.services.dialog_archive import build as build_module
from learnsys.services.dialog_archive.build import build_archive, verify_archive
from learnsys.services.dialog_archive.model import Message, Session, Source
from learnsys.services.dialog_archive.redact import redact_text
from learnsys.services.dialog_archive.render import fence_for
from learnsys.services.dialog_archive.sources import claude_code, codex, doubao


class TestRedact(unittest.TestCase):
    def test_email_phone_key_and_password(self):
        text, counts = redact_text(
            "邮箱 a@b.com 手机 13800138000 key sk-abcdefghijklmnop "
            "password=hunter2")
        self.assertNotIn("a@b.com", text)
        self.assertNotIn("13800138000", text)
        self.assertNotIn("sk-abcdefghijklmnop", text)
        self.assertNotIn("hunter2", text)
        self.assertEqual(counts["email"], 1)
        self.assertEqual(counts["phone"], 1)
        self.assertEqual(counts["api_key"], 1)
        self.assertEqual(counts["password"], 1)

    def test_fence_longer_than_content_backticks(self):
        self.assertGreater(len(fence_for("```code```")), 3)
        self.assertEqual(fence_for("普通文本"), "```")


class TestSourceFilters(unittest.TestCase):
    def test_codex_skips_environment_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "rollout-x.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"session_id": "s1"}},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text",
                                 "text": "<environment_context>机器信息"}]}},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "你好"}]}},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "在"}]}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                                      for row in rows) + "\n", encoding="utf-8")
            with mock.patch.object(codex, "ROOT", pathlib.Path(tmp)):
                result = codex.collect(9_999_999_999)
            self.assertEqual(len(result["sessions"]), 1)
            self.assertEqual([m.text for m in result["sessions"][0].messages],
                             ["你好", "在"])

    def test_claude_skips_tool_result_and_sidechain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "s.jsonl"
            rows = [
                {"type": "user", "sessionId": "s1", "message": {
                    "role": "user", "content": [
                        {"type": "tool_result", "content": "工具输出"}]}},
                {"type": "user", "sessionId": "s1", "message": {
                    "role": "user", "content": "真正的问题"}},
                {"type": "assistant", "sessionId": "s1", "message": {
                    "role": "assistant", "content": [
                        {"type": "thinking", "thinking": "内部"},
                        {"type": "text", "text": "回答"}]}},
                {"type": "user", "sessionId": "s1", "isSidechain": True,
                 "message": {"role": "user", "content": "侧链"}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                                      for row in rows) + "\n", encoding="utf-8")
            with mock.patch.object(claude_code, "ROOT", pathlib.Path(tmp)):
                result = claude_code.collect(9_999_999_999)
            self.assertEqual([m.text for m in result["sessions"][0].messages],
                             ["真正的问题", "回答"])

    def test_doubao_is_missing(self):
        result = doubao.collect(9_999_999_999)
        self.assertEqual(result["sessions"], [])
        self.assertIn("无明文导出", result["missing"])


class TestBuildSeal(unittest.TestCase):
    def _source(self):
        def collect(cutoff_ts):
            return {"files": 1, "skipped": 0, "errors": 0, "sessions": [
                Session("codex", "s1", title="测试会话", at="2026-11-04T10:00:00",
                        path="fixture.jsonl", messages=[
                            Message("user", "你好 a@b.com"),
                            Message("assistant", "在```内"),
                        ])]}
        return Source("codex", "Codex", "A", collect)

    def test_build_verify_and_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(build_module, "SOURCES", [self._source()]):
                first = build_archive(tmp)
                self.assertFalse(first["already_sealed"])
                path = pathlib.Path(first["path"])
                self.assertTrue(path.exists())
                self.assertEqual(path.stat().st_mode & 0o222, 0)
                result = verify_archive(path)
                self.assertTrue(result["ok"], result)
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("a@b.com", text)
                self.assertIn("<!-- END OF ARCHIVE -->", text)
                second = build_archive(tmp)
                self.assertTrue(second["already_sealed"])

    def test_missing_source_appears_in_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Source("doubao", "豆包", "H",
                          lambda cutoff: {"files": 0, "sessions": [],
                                          "skipped": 0, "errors": 0,
                                          "missing": "仅有二进制"},
                          missing_reason="仅有二进制")
            with mock.patch.object(build_module, "SOURCES", [fake]):
                result = build_archive(tmp)
                text = pathlib.Path(result["path"]).read_text(encoding="utf-8")
                self.assertIn("missing:", text)
                self.assertIn("仅有二进制", text)


if __name__ == "__main__":
    unittest.main()
