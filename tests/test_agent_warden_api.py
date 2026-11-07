# -*- coding: utf-8 -*-
"""P32 API：契约校验、默认契约自动挂载、验收结果随详情返回。"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server.app import create_app
from learnsys.services import agents
from learnsys.services.agents import base

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


def _script() -> str:
    return textwrap.dedent("""
        import json
        print(json.dumps({"kind": "result", "text": "完成"}, ensure_ascii=False), flush=True)
    """)


class WardenApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        store.connect(self.db).close()

        patcher = mock.patch.object(
            app_config, "USER",
            {"agents": {"allowed_roots": [str(self.root)], "timeout": 20,
                        "queue_max": 10}})
        patcher.start()
        self.addCleanup(patcher.stop)

        original_connect = store.connect
        patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: original_connect(path or self.db))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.spec = base.AgentSpec(
            id="fake", name="Fake Agent", kind="fake", command=sys.executable,
            args=["-c", _script()], available=True)

        def _spec_for(agent_id, _s=None):
            return self.spec if agent_id == "fake" else None

        for target, attr, value in (
                (agents, "spec_for", _spec_for),
                (agents.registry, "spec_for", _spec_for),
                (agents, "list_specs", lambda *a, **k: [self.spec]),
                (agents.registry, "list_specs", lambda *a, **k: [self.spec])):
            patcher = mock.patch.object(target, attr, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = mock.patch.object(app_config, "DATA_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def _create(self, **extra) -> dict:
        body = {"agent": "fake", "prompt": "读一下", "workspace": str(self.root)}
        body.update(extra)
        return self.client.post("/api/agents/tasks", json=body, headers=AUTH)

    def _wait(self, task_id: int, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.client.get(
                f"/api/agents/tasks/{task_id}", headers=AUTH).json()
            if data["task"]["status"] in ("done", "failed", "cancelled"):
                return data["task"]
            time.sleep(0.05)
        return {}

    def test_default_contract_attached_without_asking(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        task = response.json()["task"]
        self.assertTrue(task["has_contract"])
        self.assertEqual(task["verdict_state"], "")

    def test_invalid_contract_rejected(self):
        response = self._create(contract={
            "scope": {"roots": [str(self.root)]},
            "acceptance": [{"check": "我觉得对"}]})
        self.assertEqual(response.status_code, 422)
        self.assertIn("契约无效", response.json()["detail"])

    def test_contract_without_scope_rejected(self):
        response = self._create(contract={"acceptance": []})
        self.assertEqual(response.status_code, 422)

    def test_verdict_returned_in_detail(self):
        response = self._create()
        task_id = response.json()["task"]["id"]
        task = self._wait(task_id)
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["verdict_state"], "passed")
        self.assertEqual(task["verdict"]["state"], "passed")
        self.assertIsInstance(task["contract"], dict)

    def test_read_only_task_that_writes_fails(self):
        self.spec.args = ["-c", textwrap.dedent("""
            import json
            open("改动了.txt", "w", encoding="utf-8").write("x")
            print(json.dumps({"kind": "result", "text": "完成"},
                             ensure_ascii=False), flush=True)
        """)]
        response = self._create()
        task = self._wait(response.json()["task"]["id"])
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["verdict_state"], "failed")
        self.assertIn("改动了.txt", task["verdict"]["changes"]["changed"])

    def test_list_does_not_ship_verdict_body(self):
        self._create()
        data = self.client.get("/api/agents/tasks", headers=AUTH).json()
        self.assertNotIn("verdict_json", data["tasks"][0])
        self.assertIn("verdict_state", data["tasks"][0])


if __name__ == "__main__":
    unittest.main()
