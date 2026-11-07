# -*- coding: utf-8 -*-
"""派活结果 → 经验三格草稿。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class AgentExperienceDraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

        conn = store.connect()
        try:
            self.task_id = store.add_agent_task(
                conn, agent="claude", prompt="检查后端为什么 500\n看 /api/health",
                mode="read")
            conn.execute(
                "UPDATE agent_tasks SET status='done', result_text=? WHERE id=?",
                ("发现是数据库路径写错；重启后 /api/health 正常。", self.task_id))
            conn.commit()
        finally:
            conn.close()

    def test_draft_from_task(self):
        response = self.client.get(
            f"/api/agents/tasks/{self.task_id}/experience-draft", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        draft = response.json()["draft"]
        self.assertIn("检查后端", draft["title"])
        self.assertIn("检查后端", draft["scene"])
        self.assertIn("数据库路径写错", draft["pitfall"])
        self.assertEqual(draft["next_time"], "")

    def test_missing_task_404(self):
        response = self.client.get(
            "/api/agents/tasks/9999/experience-draft", headers=AUTH)
        self.assertEqual(response.status_code, 404)

    def test_requires_token(self):
        response = self.client.get(
            f"/api/agents/tasks/{self.task_id}/experience-draft")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
