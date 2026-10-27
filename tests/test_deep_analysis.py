# -*- coding: utf-8 -*-
"""深度分析：未启用时明确拒绝；命令模式可跑；审计落库；不回密钥。"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.agent import deep
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class DeepAnalysisTest(unittest.TestCase):
    def setUp(self):
        # 不读真实的 D:\学习系统\设置.json：否则本机一启用深度分析，这条就红。
        user = mock.patch.object(app_config, "USER", {"agent": {}})
        user.start()
        self.addCleanup(user.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def _configure(self, **deep_settings):
        patcher = mock.patch.dict(
            app_config.USER, {"agent": {"deep": deep_settings}}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_by_default(self):
        response = self.client.get("/api/agent/deep", headers=AUTH)
        self.assertFalse(response.json()["available"])
        run = self.client.post(
            "/api/agent/deep", json={"prompt": "解释一下"}, headers=AUTH)
        self.assertEqual(run.status_code, 409)
        self.assertIn("agent.deep", run.json()["detail"])

    def test_command_mode_runs_and_audits(self):
        script = "import sys;print('深度结果：' + sys.stdin.read())"
        self._configure(enabled=True, command=sys.executable,
                        args=["-c", script], timeout=30, api_key="secret-key")
        status = self.client.get("/api/agent/deep", headers=AUTH).json()
        self.assertTrue(status["available"])
        self.assertNotIn("secret-key", str(status))
        response = self.client.post(
            "/api/agent/deep", json={"prompt": "三次握手"}, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("深度结果：三次握手", body["text"])
        self.assertEqual(body["provider"], "command")
        runs = self.client.get(
            "/api/agent/runs?limit=10", headers=AUTH).json()["items"]
        self.assertTrue(any(row["mode"] == "deep" for row in runs))

    def test_command_failure_is_chinese(self):
        self._configure(enabled=True, command=sys.executable,
                        args=["-c", "import sys;sys.exit(3)"], timeout=30)
        response = self.client.post(
            "/api/agent/deep", json={"prompt": "试试"}, headers=AUTH)
        self.assertEqual(response.status_code, 409)
        self.assertIn("返回 3", response.json()["detail"])

    def test_missing_command_binary_is_chinese(self):
        self._configure(enabled=True, command="不存在的命令-xyz", args=[], timeout=10)
        with mock.patch.object(deep.subprocess, "run",
                               side_effect=FileNotFoundError):
            response = self.client.post(
                "/api/agent/deep", json={"prompt": "试试"}, headers=AUTH)
        self.assertEqual(response.status_code, 409)
        self.assertIn("找不到命令", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
