# -*- coding: utf-8 -*-
"""复习卡「运行代码」：薄路由只做校验，执行全交给 agent.sandbox。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.llm import config as agent_config
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class CodeRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data_root = root / "data"
        self.settings_file = root / "设置.json"
        self.db_path = root / "learning.db"
        store.connect(self.db_path).close()
        self._orig_connect = store.connect
        patches = [
            mock.patch.object(store, "connect",
                              side_effect=lambda path=None: self._orig_connect(path or self.db_path)),
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "SETTINGS_FILE", self.settings_file),
            mock.patch.object(app_config, "USER", {}),
            mock.patch.object(agent_config, "CLAUDE_SETTINGS", root / "无此文件.json"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(token=TOKEN)
        self.client = TestClient(self.app)

    def run_code(self, **body):
        return self.client.post("/api/code/run", json=body, headers=AUTH)

    def test_requires_token(self):
        resp = self.client.post("/api/code/run", json={"code": "print(1)"})
        self.assertEqual(resp.status_code, 403)

    def test_runs_python_and_returns_stdout(self):
        resp = self.run_code(language="python", code='print("学习工作台")')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["language"], "python")
        self.assertIn("学习工作台", data["stdout"])
        self.assertEqual(data["exit_code"], 0)
        self.assertFalse(data["timed_out"])

    def test_empty_code_rejected(self):
        resp = self.run_code(code="")
        self.assertEqual(resp.status_code, 422)

    def test_network_code_rejected(self):
        resp = self.run_code(language="python", code="import socket\nprint('x')")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("禁网", data["note"])

    def test_language_inferred_when_empty(self):
        resp = self.run_code(code='print("hi")')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["language"], "python")

    def test_stdin_passed(self):
        code = "print(input().strip().upper())"
        resp = self.run_code(language="python", code=code, stdin="abc\n")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("ABC", data["stdout"])

    def test_runtime_error_keeps_stderr(self):
        resp = self.run_code(language="python", code="raise ValueError('坏了')")
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertNotEqual(data["exit_code"], 0)
        self.assertTrue(data["note"] or data["stderr"])


if __name__ == "__main__":
    unittest.main()
