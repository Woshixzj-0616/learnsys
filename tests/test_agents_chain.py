# -*- coding: utf-8 -*-
"""P26.4 显式任务链：依赖认领、结果注入、失败级联、长度口径。"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.services import agents
from learnsys.services.agents import base, queue

PARENT_TEXT = "父结果内容"


def _parent_script(sleep_s: float = 0.25) -> str:
    return textwrap.dedent(f"""
        import json, time
        time.sleep({sleep_s})
        print(json.dumps({{"kind": "text", "text": {PARENT_TEXT!r}}}, ensure_ascii=False), flush=True)
        print(json.dumps({{"kind": "result", "text": ""}}, ensure_ascii=False), flush=True)
    """)


def _echo_script() -> str:
    return textwrap.dedent("""
        import json, sys
        print(json.dumps({"kind": "text", "text": sys.argv[-1]}, ensure_ascii=False), flush=True)
        print(json.dumps({"kind": "result", "text": ""}, ensure_ascii=False), flush=True)
    """)


def _fail_script() -> str:
    return "import sys\nsys.exit(3)\n"


def _big_script(size: int) -> str:
    return textwrap.dedent(f"""
        import json
        print(json.dumps({{"kind": "text", "text": "x" * {size}}}, ensure_ascii=False), flush=True)
        print(json.dumps({{"kind": "result", "text": ""}}, ensure_ascii=False), flush=True)
    """)


def _spec(agent_id: str, script: str, available: bool = True,
          note: str = "") -> base.AgentSpec:
    return base.AgentSpec(
        id=agent_id, name=agent_id.title(), kind="fake", command=sys.executable,
        args=["-c", script], available=available, note=note)


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)
        self.user = mock.patch.object(
            app_config, "USER",
            {"agents": {"timeout": 20, "max_concurrent": 2, "queue_max": 20}})
        self.user.start()
        self.addCleanup(self.user.stop)
        self.root_patch = mock.patch.object(app_config, "DATA_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        original = store.connect
        self.connect_patch = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: original(path or self.db))
        self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.specs = {
            "alpha": _spec("alpha", _parent_script()),
            "beta": _spec("beta", _echo_script()),
        }
        self.spec_patch = mock.patch.object(
            agents.registry, "spec_for",
            side_effect=lambda agent_id, _s=None: self.specs.get(agent_id))
        self.spec_patch.start()
        self.addCleanup(self.spec_patch.stop)

    def _add(self, agent: str, prompt: str, depends_on: int = 0) -> int:
        task_id = store.add_agent_queued_task(
            self.conn, agent=agent, prompt=prompt, workspace=str(self.root),
            depends_on=depends_on)
        self.assertIsNotNone(task_id)
        return int(task_id)

    def _wait(self, task_id: int, timeout: float = 12) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = store.get_agent_task(self.conn, task_id)
            if task and task["status"] in ("done", "failed", "cancelled"):
                return task
            time.sleep(0.05)
        return store.get_agent_task(self.conn, task_id) or {}

    def _output(self, task: dict) -> str:
        path = self.root / str(task.get("output_path") or "")
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_child_waits_for_parent_and_gets_result(self):
        parent = self._add("alpha", "第一步")
        child = self._add("beta", "第二步：复述上一步", depends_on=parent)
        queue.schedule_drain()
        task = store.get_agent_task(self.conn, child)
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["parent_status"], "running")
        self.assertEqual(self._wait(parent)["status"], "done")
        child_task = self._wait(child)
        self.assertEqual(child_task["status"], "done", child_task)
        self.assertEqual(store.get_agent_task(self.conn, child)["prompt"],
                         "第二步：复述上一步")
        output = self._output(child_task)
        self.assertIn("【上一步任务 #{} 的结果".format(parent), output)
        self.assertIn(PARENT_TEXT, output)
        self.assertIn("第二步：复述上一步", output)

    def test_independent_task_overtakes_blocked_child(self):
        app_config.USER["agents"]["max_concurrent"] = 2
        self.specs["alpha"] = _spec("alpha", _parent_script(0.8))
        parent = self._add("alpha", "慢父任务")
        child = self._add("beta", "等父任务", depends_on=parent)
        independent = self._add("beta", "独立任务")
        queue.schedule_drain()
        tasks = {task["id"]: task for task in store.list_agent_tasks(self.conn)}
        self.assertEqual(tasks[parent]["status"], "running")
        self.assertEqual(tasks[child]["status"], "queued")
        self.assertEqual(tasks[independent]["status"], "running")
        self.assertEqual(self._wait(child)["status"], "done")
        self.assertEqual(self._wait(independent)["status"], "done")

    def test_parent_failure_cancels_child(self):
        self.specs["alpha"] = _spec("alpha", _fail_script())
        parent = self._add("alpha", "会失败")
        child = self._add("beta", "子任务", depends_on=parent)
        queue.schedule_drain()
        self.assertEqual(self._wait(parent)["status"], "failed")
        child_task = self._wait(child)
        self.assertEqual(child_task["status"], "cancelled")
        self.assertEqual(child_task["started_at"], "")
        self.assertIn("链已停止", child_task["error"])

    def test_grandchild_cascade(self):
        self.specs["alpha"] = _spec("alpha", _fail_script())
        first = self._add("alpha", "第一层失败")
        second = self._add("beta", "第二层", depends_on=first)
        third = self._add("beta", "第三层", depends_on=second)
        queue.schedule_drain()
        self.assertEqual(self._wait(first)["status"], "failed")
        self.assertEqual(self._wait(second)["status"], "cancelled")
        self.assertEqual(self._wait(third)["status"], "cancelled")

    def test_orphan_parent_is_cancelled(self):
        # add_queued 会拦住不存在的父任务；这里直接落库模拟脏数据
        orphan = store.add_agent_task(
            self.conn, agent="beta", prompt="父任务不存在",
            workspace=str(self.root), depends_on=9999)
        queue.schedule_drain()
        task = self._wait(orphan)
        self.assertEqual(task["status"], "cancelled")
        self.assertIn("链已停止", task["error"])

    def test_cancel_running_parent_cancels_child(self):
        self.specs["alpha"] = _spec("alpha", _parent_script(5))
        parent = self._add("alpha", "长任务")
        child = self._add("beta", "子任务", depends_on=parent)
        queue.schedule_drain()
        time.sleep(0.3)
        self.assertTrue(queue.cancel(parent))
        self.assertEqual(self._wait(parent)["status"], "cancelled")
        self.assertEqual(self._wait(child)["status"], "cancelled")

    def test_unavailable_agent_fails_and_cascades_same_pass(self):
        self.specs["alpha"] = _spec("alpha", "", available=False, note="中转口未启动")
        parent = self._add("alpha", "不可用")
        child = self._add("beta", "子任务", depends_on=parent)
        queue.schedule_drain()
        self.assertEqual(self._wait(parent)["status"], "failed")
        self.assertEqual(self._wait(child)["status"], "cancelled")

    def test_result_text_persisted_and_truncated(self):
        self.specs["alpha"] = _spec("alpha", _big_script(30000))
        task_id = self._add("alpha", "大结果")
        queue.schedule_drain()
        task = self._wait(task_id)
        self.assertEqual(task["status"], "done")
        self.assertTrue(task["has_result"])
        self.assertNotIn("result_text", task)
        self.assertEqual(len(store.get_agent_task_result(self.conn, task_id)), 20000)

    def test_old_task_without_result_has_no_result_flag(self):
        task_id = store.add_agent_task(
            self.conn, agent="alpha", prompt="老任务")
        store.update_agent_task(self.conn, task_id, status="done", duration_ms=1)
        task = store.get_agent_task(self.conn, task_id)
        self.assertFalse(task["has_result"])


class ComposeChainPromptTest(unittest.TestCase):
    def test_empty_result_gets_placeholder(self):
        text = queue.compose_chain_prompt("做第二步", 3, "")
        self.assertIn("（上一步没有文本结果）", text)
        self.assertTrue(text.endswith("做第二步"))

    def test_total_length_and_truncation_keeps_prompt(self):
        prompt = "原任务" * 1000
        result = "结果" * 10000
        text = queue.compose_chain_prompt(prompt, 8, result)
        self.assertLessEqual(len(text), queue.MAX_RUN_PROMPT)
        self.assertIn("已截断", text)
        self.assertTrue(text.endswith(prompt))
        self.assertIn("【上一步任务 #8 的结果", text)

    def test_short_result_not_truncated(self):
        text = queue.compose_chain_prompt("短任务", 1, "短结果")
        self.assertNotIn("已截断", text)
        self.assertIn("短结果", text)
        self.assertLessEqual(len(text), queue.MAX_RUN_PROMPT)


if __name__ == "__main__":
    unittest.main()
