# -*- coding: utf-8 -*-
"""摘要防污染：未验证的候选不许写成「根因是 / 已解决」。"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import store
from learnsys.agent import post_turn
from learnsys.llm.config import AgentConfig
from learnsys.llm.provider_anthropic import ProviderEvent, ProviderResult


def make_cfg(root: pathlib.Path, **overrides) -> AgentConfig:
    return AgentConfig(
        base_url="http://127.0.0.1:9/v1",
        auth_token="test-token",
        model="test-model",
        fast_model="test-fast",
        max_tokens=1024,
        thinking=False,
        vision_base_url="", vision_api_key="", vision_model="glm-4v-flash",
        data_root=root, profile_path=root / "学习档案.md",
        **overrides,
    )


def fake_stream(payload: dict):
    text = json.dumps(payload, ensure_ascii=False)

    def stream(cfg, system, messages, tools, *, abort=None, response_sink=None,
               **kwargs):
        yield ProviderEvent("text", text)
        yield ProviderEvent("done", result=ProviderResult(
            text=text, stop_reason="end_turn"))

    return stream


class SummarySanitizeTest(unittest.TestCase):
    def test_absolute_without_label_gets_marker(self):
        text = post_turn._sanitize_summary("根因是默认站点接管了 80 端口。")
        self.assertIn("未验证", text)

    def test_absolute_with_label_is_kept(self):
        text = "候选：默认站点接管了 80 端口（未验证）。"
        self.assertEqual(post_turn._sanitize_summary(text), text)

    def test_plain_summary_unchanged(self):
        text = "用户在学 nginx，已经弄清了 listen 分组。"
        self.assertEqual(post_turn._sanitize_summary(text), text)

    def test_system_prompt_mentions_grading(self):
        self.assertIn("候选", post_turn.SYSTEM)
        self.assertIn("未验证", post_turn.SYSTEM)


class SummaryGuardWiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.conn = store.connect(self.root / "learning.db")
        self.addCleanup(self.conn.close)

    def _run(self, cfg: AgentConfig, summary: str) -> dict:
        conv_id = store.create_conversation(self.conn, title="测试", module="ask")
        for index in range(4):
            store.add_message(self.conn, conv_id,
                              "user" if index % 2 == 0 else "assistant",
                              {"text": f"第{index}条"})
        with mock.patch.object(post_turn, "load_config", return_value=cfg), \
                mock.patch.object(post_turn.provider_anthropic, "stream_messages",
                                  side_effect=fake_stream(
                                      {"summary": summary, "memories": []})):
            result = post_turn.run_once(conv_id, self.root)
        return {"result": result, "row": store.get_conversation(self.conn, conv_id)}

    def test_guard_on_appends_marker(self):
        data = self._run(make_cfg(self.root), "根因是 nginx 没有 reload。")
        self.assertIn("未验证", data["result"]["summary"])
        self.assertIn("未验证", data["row"][4])

    def test_guard_off_keeps_summary(self):
        data = self._run(make_cfg(self.root, summary_guard=False),
                         "根因是 nginx 没有 reload。")
        self.assertEqual(data["result"]["summary"], "根因是 nginx 没有 reload。")
        self.assertNotIn("未验证", data["row"][4])


if __name__ == "__main__":
    unittest.main(verbosity=2)
