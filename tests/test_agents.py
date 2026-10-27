# -*- coding: utf-8 -*-
"""P26.1 Agent 中枢：只读参数、解析、工作目录、任务生命周期、API。"""
from __future__ import annotations

import json
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
from learnsys.services.agents import base, runner, workspace as workspace_mod

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


def _fake_script() -> str:
    return textwrap.dedent("""
        import json, sys
        print(json.dumps({"kind": "status", "text": "开始"}, ensure_ascii=False), flush=True)
        print(json.dumps({"kind": "text", "text": "第一条结论"}, ensure_ascii=False), flush=True)
        print(json.dumps({"kind": "tool", "text": "Read a.txt"}, ensure_ascii=False), flush=True)
        print(json.dumps({"kind": "text", "text": "第二条结论"}, ensure_ascii=False), flush=True)
        print(json.dumps({"kind": "result", "text": "", "usage": {"input_tokens": 3},
                          "cost_usd": 0.01}, ensure_ascii=False), flush=True)
    """)


def _sleep_script(seconds: float = 30) -> str:
    return f"import time\ntime.sleep({seconds})\n"


def _fake_spec(script: str) -> base.AgentSpec:
    return base.AgentSpec(
        id="fake", name="Fake Agent", kind="fake", command=sys.executable,
        args=["-c", script], available=True)


class AgentBaseTest(unittest.TestCase):
    def test_claude_argv_is_read_only(self):
        spec = base.AgentSpec(id="claude", name="Claude", kind="claude",
                              command="claude")
        argv = base.build_argv(spec, "只读", r"D:\Desktop\learnsys")
        joined = " ".join(argv)
        self.assertIn("--restricted", argv)
        self.assertIn("plan", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("bypassPermissions", joined)
        self.assertIn(r"D:\Desktop\learnsys", argv)

    def test_codex_argv_is_read_only(self):
        spec = base.AgentSpec(id="codex", name="Codex", kind="codex",
                              command="codex")
        argv = base.build_argv(spec, "只读", r"D:\Desktop\learnsys")
        self.assertIn("read-only", argv)
        self.assertIn("--ephemeral", argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

    def test_parse_claude_text_tool_and_result(self):
        text_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "结论"}]}})
        tool_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read",
                                     "input": {"file_path": "a.txt"}}]}})
        result_line = json.dumps({"total_cost_usd": 0.02,
                                  "usage": {"input_tokens": 10}})
        events = base.parse_line("claude", text_line)
        self.assertEqual(events[0].kind, "text")
        self.assertEqual(events[0].text, "结论")
        events = base.parse_line("claude", tool_line)
        self.assertEqual(events[0].kind, "tool")
        self.assertIn("Read", events[0].text)
        events = base.parse_line("claude", result_line)
        self.assertEqual(events[0].kind, "result")
        self.assertAlmostEqual(events[0].cost_usd, 0.02)

    def test_parse_codex_message(self):
        line = json.dumps({"type": "item.completed",
                           "item": {"type": "agent_message", "text": "答案"}})
        events = base.parse_line("codex", line)
        self.assertEqual(events[0].kind, "text")
        self.assertEqual(events[0].text, "答案")


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.settings = {"allowed_roots": [str(self.root)]}

    def test_inside_allowed(self):
        path, error = workspace_mod.resolve_workspace(str(self.root), self.settings)
        self.assertEqual(error, "")
        self.assertEqual(path, self.root.resolve())

    def test_outside_rejected(self):
        _path, error = workspace_mod.resolve_workspace(
            str(self.root.parent), self.settings)
        self.assertIn("不在允许列表", error)

    def test_unc_rejected(self):
        _path, error = workspace_mod.resolve_workspace(
            r"\\server\share", self.settings)
        self.assertIn("网络路径", error)

    def test_missing_rejected(self):
        _path, error = workspace_mod.resolve_workspace(
            str(self.root / "nope"), self.settings)
        self.assertIn("不存在", error)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

    def _wait(self, task_id: int, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = store.get_agent_task(self.conn, task_id)
            if task and task["status"] in ("done", "failed", "cancelled"):
                return task
            time.sleep(0.05)
        return store.get_agent_task(self.conn, task_id) or {}

    def test_lifecycle_saves_output_and_events(self):
        task_id = store.add_agent_task(
            self.conn, agent="fake", prompt="读一下 a.txt", workspace=str(self.root))
        runner.start_task(task_id, _fake_spec(_fake_script()), "读一下 a.txt",
                          self.root, 20, self.root, db_path=self.db)
        task = self._wait(task_id)
        self.assertEqual(task["status"], "done", task)
        self.assertTrue(task["output_path"])
        output = self.root / task["output_path"]
        self.assertTrue(output.exists())
        text = output.read_text(encoding="utf-8")
        self.assertIn("读一下 a.txt", text)
        self.assertIn("第一条结论", text)
        events = store.list_agent_task_events(self.conn, task_id)
        kinds = [event["kind"] for event in events]
        self.assertIn("text", kinds)
        self.assertIn("tool", kinds)
        self.assertIn("status", kinds)

    def test_cancel(self):
        task_id = store.add_agent_task(
            self.conn, agent="fake", prompt="睡一会", workspace=str(self.root))
        runner.start_task(task_id, _fake_spec(_sleep_script(30)), "睡一会",
                          self.root, 60, self.root, db_path=self.db)
        time.sleep(0.3)
        self.assertTrue(runner.cancel_task(task_id))
        task = self._wait(task_id)
        self.assertEqual(task["status"], "cancelled", task)

    def test_timeout(self):
        task_id = store.add_agent_task(
            self.conn, agent="fake", prompt="睡一会", workspace=str(self.root))
        runner.start_task(task_id, _fake_spec(_sleep_script(30)), "睡一会",
                          self.root, 1, self.root, db_path=self.db)
        task = self._wait(task_id, timeout=10)
        self.assertEqual(task["status"], "failed", task)
        self.assertIn("超过", task["error"])


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        store.connect(self.db).close()
        self.user = mock.patch.object(
            app_config, "USER",
            {"agents": {"allowed_roots": [str(self.root)], "timeout": 20}})
        self.user.start()
        self.addCleanup(self.user.stop)
        original_connect = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: original_connect(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.spec = _fake_spec(_fake_script())
        self.patcher_spec = mock.patch.object(agents, "spec_for",
                                              side_effect=lambda agent_id, _s=None:
                                              self.spec if agent_id == "fake" else None)
        self.patcher_spec.start()
        self.addCleanup(self.patcher_spec.stop)
        self.patcher_list = mock.patch.object(agents, "list_specs",
                                              return_value=[self.spec])
        self.patcher_list.start()
        self.addCleanup(self.patcher_list.stop)
        self.patcher_root = mock.patch.object(
            app_config, "DATA_ROOT", self.root)
        self.patcher_root.start()
        self.addCleanup(self.patcher_root.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_list_agents(self):
        data = self.client.get("/api/agents", headers=AUTH).json()
        self.assertEqual(data["agents"][0]["id"], "fake")
        self.assertTrue(data["agents"][0]["available"])
        self.assertIn(str(self.root), data["allowed_roots"])

    def test_create_and_poll_task(self):
        response = self.client.post(
            "/api/agents/tasks",
            json={"agent": "fake", "prompt": "读一下", "workspace": str(self.root)},
            headers=AUTH)
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task"]["id"]
        deadline = time.monotonic() + 10
        payload = {}
        while time.monotonic() < deadline:
            payload = self.client.get(
                f"/api/agents/tasks/{task_id}/events?after=0",
                headers=AUTH).json()
            if payload["task"]["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(payload["task"]["status"], "done", payload)
        kinds = [event["kind"] for event in payload["events"]]
        self.assertIn("text", kinds)
        self.assertTrue(payload["task"]["output_path"])

    def test_outside_workspace_400(self):
        response = self.client.post(
            "/api/agents/tasks",
            json={"agent": "fake", "prompt": "读一下",
                  "workspace": str(self.root.parent)},
            headers=AUTH)
        self.assertEqual(response.status_code, 400, response.text)

    def test_unavailable_agent_409(self):
        self.spec.available = False
        self.spec.note = "没装"
        response = self.client.post(
            "/api/agents/tasks",
            json={"agent": "fake", "prompt": "读一下", "workspace": str(self.root)},
            headers=AUTH)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("没装", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
