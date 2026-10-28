# -*- coding: utf-8 -*-
"""P26.1 Agent 中枢：只读参数、解析、工作目录、任务生命周期、API。"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server.app import create_app
from learnsys.services import agents
from learnsys.services.agents import approvals, base, runner
from learnsys.services.agents import workspace as workspace_mod

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

    def test_claude_write_argv_has_per_tool_hook(self):
        spec = base.AgentSpec(id="claude", name="Claude", kind="claude",
                              command="claude")
        settings = approvals.hook_settings(pathlib.Path(r"D:\数据\approve.cmd"), 30)
        argv = base.build_argv(spec, "改文件", r"D:\Desktop\learnsys",
                               mode="write", settings_json=settings)
        joined = " ".join(argv)
        self.assertIn("--restricted", argv)
        self.assertIn("--settings", argv)
        self.assertIn("approve.cmd", joined)
        self.assertIn("PreToolUse", joined)
        self.assertIn("Bash", argv[argv.index("--tools") + 1])
        self.assertNotIn("bypassPermissions", joined)
        self.assertIn("default", argv)
        self.assertTrue(json.loads(settings)["hooks"]["PreToolUse"])

    def test_codex_write_argv_uses_workspace_sandbox(self):
        spec = base.AgentSpec(id="codex", name="Codex", kind="codex",
                              command="codex")
        argv = base.build_argv(spec, "改文件", r"D:\Desktop\learnsys",
                               mode="write")
        self.assertIn("workspace-write", argv)
        self.assertNotIn("danger-full-access", argv)
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


class ApprovalDescribeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_write_new_file(self):
        info = approvals.describe(
            "Write", {"file_path": str(self.root / "a.txt"), "content": "hi"})
        self.assertEqual(info["kind"], "write")
        self.assertIn("新建文件", info["summary"])
        self.assertIn("hi", info["preview"])
        self.assertIn("a.txt", info["target"])

    def test_edit_shows_diff(self):
        path = self.root / "a.txt"
        path.write_text("one\ntwo\n", encoding="utf-8")
        info = approvals.describe("Edit", {
            "file_path": str(path), "old_string": "two",
            "new_string": "three"})
        self.assertEqual(info["kind"], "edit")
        self.assertIn("-two", info["preview"])
        self.assertIn("+three", info["preview"])
        self.assertIn("1 处", info["summary"])

    def test_bash_summary(self):
        info = approvals.describe(
            "Bash", {"command": "dir", "description": "看目录"})
        self.assertEqual(info["kind"], "command")
        self.assertIn("dir", info["summary"])
        self.assertIn("看目录", info["preview"])

    def test_hook_settings_and_command(self):
        cmd_path = approvals.ensure_hook_cmd(self.root)
        self.assertTrue(cmd_path.exists())
        text = cmd_path.read_text(encoding="utf-8")
        self.assertIn("%LEARNSYS_HOOK_TOKEN%", text)
        self.assertIn("curl.exe", text)
        settings = json.loads(approvals.hook_settings(cmd_path, 30))
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertIn("Write", hook["matcher"])
        self.assertIn("Bash", hook["matcher"])
        self.assertEqual(hook["hooks"][0]["timeout"], 30)
        self.assertIn("approve.cmd", hook["hooks"][0]["command"])

    def test_unknown_tool_is_still_described(self):
        info = approvals.describe("SomeTool", {"x": 1})
        self.assertEqual(info["kind"], "other")
        self.assertIn("SomeTool", info["summary"])


class ApprovalStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = pathlib.Path(self.tmp.name) / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)
        self.task_id = store.add_agent_task(
            self.conn, agent="fake", prompt="写", workspace=str(self.tmp.name))

    def test_pending_to_allowed_once(self):
        approval_id = store.add_agent_approval(
            self.conn, task_id=self.task_id, tool="Write", kind="write",
            summary="新建 a.txt", preview="hi")
        self.assertEqual(len(store.pending_agent_approvals(
            self.conn, self.task_id)), 1)
        self.assertTrue(store.decide_agent_approval(
            self.conn, approval_id, "allowed", "同意"))
        self.assertFalse(store.decide_agent_approval(
            self.conn, approval_id, "denied", "反悔"))
        row = store.get_agent_approval(self.conn, approval_id)
        self.assertEqual(row["status"], "allowed")
        self.assertEqual(row["reason"], "同意")
        self.assertEqual(len(store.pending_agent_approvals(
            self.conn, self.task_id)), 0)
        summary = store.agent_approvals_summary(self.conn, self.task_id)
        self.assertEqual(summary[0]["status"], "allowed")
        self.assertNotIn("payload_json", summary[0])


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        store.connect(self.db).close()
        self.user = mock.patch.object(
            app_config, "USER",
            {"agents": {"allowed_roots": [str(self.root)], "timeout": 20,
                        "approval_timeout": 1}})
        self.user.start()
        self.addCleanup(self.user.stop)
        original_connect = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: original_connect(path or self.db))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.spec = _fake_spec(_fake_script())
        def _spec_for(agent_id, _s=None):
            return self.spec if agent_id == "fake" else None

        self.patcher_spec = mock.patch.object(agents, "spec_for",
                                              side_effect=_spec_for)
        self.patcher_spec.start()
        self.addCleanup(self.patcher_spec.stop)
        # 队列直接读 registry，不经过包级别名，两个落点都要 patch
        self.patcher_registry_spec = mock.patch.object(
            agents.registry, "spec_for", side_effect=_spec_for)
        self.patcher_registry_spec.start()
        self.addCleanup(self.patcher_registry_spec.stop)
        self.patcher_list = mock.patch.object(agents, "list_specs",
                                              return_value=[self.spec])
        self.patcher_list.start()
        self.addCleanup(self.patcher_list.stop)
        self.patcher_registry_list = mock.patch.object(
            agents.registry, "list_specs", return_value=[self.spec])
        self.patcher_registry_list.start()
        self.addCleanup(self.patcher_registry_list.stop)
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

    def test_second_task_queues_instead_of_409(self):
        self.spec = _fake_spec(_sleep_script(1))
        body = {"agent": "fake", "prompt": "睡一下", "workspace": str(self.root)}
        first = self.client.post("/api/agents/tasks", json=body, headers=AUTH)
        second = self.client.post("/api/agents/tasks", json=body, headers=AUTH)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["task"]["status"], "queued")
        self.assertEqual(second.json()["queue_position"], 1)
        for task_id in (first.json()["task"]["id"], second.json()["task"]["id"]):
            deadline = time.monotonic() + 15
            status = ""
            while time.monotonic() < deadline:
                status = self.client.get(
                    f"/api/agents/tasks/{task_id}", headers=AUTH).json()[
                        "task"]["status"]
                if status in ("done", "failed", "cancelled"):
                    break
                time.sleep(0.05)
            self.assertEqual(status, "done")

    def test_queue_full_429(self):
        app_config.USER["agents"]["queue_max"] = 1
        self.spec = _fake_spec(_sleep_script(1))
        body = {"agent": "fake", "prompt": "睡一下", "workspace": str(self.root)}
        codes = [self.client.post("/api/agents/tasks", json=body,
                                  headers=AUTH).status_code for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            tasks = self.client.get("/api/agents/tasks?limit=10",
                                    headers=AUTH).json()["tasks"]
            if all(item["status"] in ("done", "failed", "cancelled")
                   for item in tasks):
                break
            time.sleep(0.05)

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

    def _write_task(self) -> int:
        conn = store.connect()
        try:
            return store.add_agent_task(
                conn, agent="fake", prompt="写一点东西",
                workspace=str(self.root), mode="write")
        finally:
            conn.close()

    def _hook_headers(self, token: str, task_id: int) -> dict:
        return {"X-Learnsys-Hook": token, "X-Learnsys-Task": str(task_id)}

    def test_approval_list_and_decide(self):
        task_id = self._write_task()
        conn = store.connect()
        try:
            approval_id = store.add_agent_approval(
                conn, task_id=task_id, tool="Write", kind="write",
                summary="新建 a.txt", preview="hi")
        finally:
            conn.close()
        data = self.client.get(
            f"/api/agents/tasks/{task_id}/approvals", headers=AUTH).json()
        self.assertEqual(data["approvals"][0]["status"], "pending")
        response = self.client.post(
            f"/api/agents/approvals/{approval_id}/decide",
            json={"decision": "allow"}, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["approval"]["status"], "allowed")
        again = self.client.post(
            f"/api/agents/approvals/{approval_id}/decide",
            json={"decision": "deny"}, headers=AUTH)
        self.assertEqual(again.status_code, 409, again.text)

    def test_hook_rejects_unknown_token(self):
        task_id = self._write_task()
        response = self.client.post(
            "/api/agents/hooks/approval",
            json={"tool_name": "Write",
                  "tool_input": {"file_path": "x", "content": "y"}},
            headers=self._hook_headers("bad-token", task_id))
        self.assertEqual(response.status_code, 403, response.text)

    def test_hook_waits_for_user_allow(self):
        task_id = self._write_task()
        token = approvals.register(task_id)
        self.addCleanup(approvals.unregister, token)
        result = {}

        def hook():
            result["response"] = self.client.post(
                "/api/agents/hooks/approval",
                json={"tool_name": "Write",
                      "tool_input": {"file_path": str(self.root / "a.txt"),
                                     "content": "hi"}},
                headers=self._hook_headers(token, task_id))

        worker = threading.Thread(target=hook)
        worker.start()
        deadline = time.monotonic() + 5
        approval = None
        while time.monotonic() < deadline:
            conn = store.connect()
            try:
                rows = store.pending_agent_approvals(conn, task_id)
            finally:
                conn.close()
            if rows:
                approval = rows[0]
                break
            time.sleep(0.05)
        self.assertIsNotNone(approval, "钩子没有落提议")
        decided = self.client.post(
            f"/api/agents/approvals/{approval['id']}/decide",
            json={"decision": "allow"}, headers=AUTH)
        self.assertEqual(decided.status_code, 200, decided.text)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        payload = result["response"].json()
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_hook_timeout_denies(self):
        task_id = self._write_task()
        token = approvals.register(task_id)
        self.addCleanup(approvals.unregister, token)
        started = time.monotonic()
        response = self.client.post(
            "/api/agents/hooks/approval",
            json={"tool_name": "Bash", "tool_input": {"command": "dir"}},
            headers=self._hook_headers(token, task_id))
        elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertLess(elapsed, 15)
        conn = store.connect()
        try:
            rows = store.list_agent_approvals(conn, task_id)
        finally:
            conn.close()
        self.assertEqual(rows[0]["status"], "expired")


if __name__ == "__main__":
    unittest.main()
