# -*- coding: utf-8 -*-
"""v1 直连后端也要记模型账 —— 与工作台共用同一本 `model_usage`。

托盘里的「今日素材 / 术语表」走 `ask.backend`，不走 `agent.run`；
不补记账的话，这部分花费不会进成本面板，也不受每日上限约束。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys.agent import usage as agent_usage  # noqa: E402
from learnsys.ask import backend  # noqa: E402


class _Resp:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def close(self):
        pass


def _chat_payload(usage=None) -> dict:
    data = {"choices": [{"message": {"content": "答案"}}]}
    if usage is not None:
        data["usage"] = usage
    return data


class BackendUsageTest(unittest.TestCase):
    def test_chat_style_usage_is_recorded(self):
        usage = {"prompt_tokens": 120, "completion_tokens": 30}
        with mock.patch.object(backend, "_open", return_value=_Resp(_chat_payload(usage))), \
             mock.patch.object(backend.config, "api_style", return_value="chat"), \
             mock.patch.object(agent_usage, "record") as record:
            text = backend.ask(None, "问", None)
        self.assertEqual(text, "答案")
        record.assert_called_once()
        kwargs = record.call_args.kwargs
        self.assertEqual(kwargs["source"], "desktop")
        self.assertEqual(kwargs["usage"], usage)
        self.assertEqual(kwargs["model"], backend.config.ASK_API_MODEL)

    def test_responses_style_usage_is_recorded(self):
        payload = {
            "output_text": "答案",
            "response": {"usage": {"input_tokens": 80, "output_tokens": 20}},
        }
        with mock.patch.object(backend, "_open", return_value=_Resp(payload)), \
             mock.patch.object(backend.config, "api_style", return_value="responses"), \
             mock.patch.object(agent_usage, "record") as record:
            backend.ask(None, "问", None)
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["usage"],
                         {"input_tokens": 80, "output_tokens": 20})

    def test_no_usage_does_not_record(self):
        with mock.patch.object(backend, "_open", return_value=_Resp(_chat_payload())), \
             mock.patch.object(backend.config, "api_style", return_value="chat"), \
             mock.patch.object(agent_usage, "record") as record:
            backend.ask(None, "问", None)
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
