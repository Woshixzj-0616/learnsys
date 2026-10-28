# -*- coding: utf-8 -*-
"""P26.3 Agent 中枢队列：入队、原子认领、串行、取消、恢复。"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

from learnsys import config as app_config
from learnsys import store
from learnsys.services import agents
from learnsys.services.agents import base, queue


def _script(sleep_s: float = 0.0) -> str:
    return textwrap.dedent(f"""
        import json, time
        time.sleep({sleep_s})
        print(json.dumps({{"kind": "status", "text": "开始"}}, ensure_ascii=False), flush=True)
        print(json.dumps({{"kind": "text", "text": "结论"}}, ensure_ascii=False), flush=True)
        print(json.dumps({{"kind": "result", "text": ""}}, ensure_ascii=False), flush=True)
    """)


def _spec(agent_id: str, sleep_s: float = 0.0, available: bool = True,
          note: str = "") -> base.AgentSpec:
    return base.AgentSpec(
        id=agent_id, name=agent_id.title(), kind="fake", command=sys.executable,
        args=["-c", _script(sleep_s)], available=available, note=note)


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)
        self.user = mock.patch.object(
            app_config, "USER",
            {"agents": {"timeout": 20, "max_concurrent": 2, "queue_max": 10}})
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
        self.specs = {"alpha": _spec("alpha", 0.5), "beta": _spec("beta", 0.1)}
        self.spec_patch = mock.patch.object(
            agents.registry, "spec_for",
            side_effect=lambda agent_id, _s=None: self.specs.get(agent_id))
        self.spec_patch.start()
        self.addCleanup(self.spec_patch.stop)

    def _enqueue(self, agent: str, prompt: str = "任务") -> int:
        task_id = store.add_agent_queued_task(
            self.conn, agent=agent, prompt=prompt, workspace=str(self.root))
        self.assertIsNotNone(task_id)
        return int(task_id)

    def _wait(self, task_id: int, timeout: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = store.get_agent_task(self.conn, task_id)
            if task and task["status"] in ("done", "failed", "cancelled"):
                return task
            time.sleep(0.05)
        return store.get_agent_task(self.conn, task_id) or {}

    def test_same_agent_queues_and_resumes(self):
        first = self._enqueue("alpha", "第一条")
        second = self._enqueue("alpha", "第二条")
        queue.schedule_drain()
        tasks = {task["id"]: task for task in store.list_agent_tasks(self.conn)}
        self.assertEqual(tasks[first]["status"], "running")
        self.assertEqual(tasks[second]["status"], "queued")
        self.assertEqual(tasks[second]["queue_position"], 1)
        self.assertEqual(self._wait(first)["status"], "done")
        self.assertEqual(self._wait(second)["status"], "done")
        started = store.get_agent_task(self.conn, second)
        self.assertTrue(started["started_at"])

    def test_global_concurrency_one(self):
        app_config.USER["agents"]["max_concurrent"] = 1
        self.specs["alpha"] = _spec("alpha", 0.4)
        self.specs["beta"] = _spec("beta", 0.1)
        alpha = self._enqueue("alpha")
        beta = self._enqueue("beta")
        queue.schedule_drain()
        tasks = {task["id"]: task for task in store.list_agent_tasks(self.conn)}
        running = [task for task in tasks.values() if task["status"] == "running"]
        self.assertEqual(len(running), 1)
        self.assertEqual(tasks[alpha]["status"], "running")
        self.assertEqual(tasks[beta]["status"], "queued")
        self.assertEqual(self._wait(alpha)["status"], "done")
        self.assertEqual(self._wait(beta)["status"], "done")

    def test_queue_full_returns_none(self):
        app_config.USER["agents"]["queue_max"] = 1
        self.assertIsNotNone(store.add_agent_queued_task(
            self.conn, agent="alpha", prompt="一", workspace=str(self.root),
            queue_max=1))
        self.assertIsNone(store.add_agent_queued_task(
            self.conn, agent="alpha", prompt="二", workspace=str(self.root),
            queue_max=1))

    def test_claim_is_atomic_across_connections(self):
        task_id = self._enqueue("alpha")
        other = store.connect(self.db)
        self.addCleanup(other.close)
        results: list[int | None] = []

        def _claim(conn):
            results.append(store.claim_agent_task(conn, max_global=2))

        threads = [threading.Thread(target=_claim, args=(self.conn,)),
                   threading.Thread(target=_claim, args=(other,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        wins = [item for item in results if item is not None]
        self.assertEqual(wins, [task_id])
        self.assertEqual(store.get_agent_task(self.conn, task_id)["status"], "running")
        queue.cancel(task_id)

    def test_cancel_queued_and_next_still_runs(self):
        first = self._enqueue("alpha", "慢任务")
        second = self._enqueue("alpha", "排队任务")
        queue.schedule_drain()
        self.assertTrue(queue.cancel(second))
        task = store.get_agent_task(self.conn, second)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["started_at"], "")
        kinds = [event["kind"] for event in
                 store.list_agent_task_events(self.conn, second)]
        self.assertIn("status", kinds)
        self.assertEqual(self._wait(first)["status"], "done")
        time.sleep(0.2)
        self.assertEqual(store.get_agent_task(self.conn, second)["status"], "cancelled")

    def test_cancel_before_drain_never_starts(self):
        task_id = self._enqueue("alpha")
        self.assertTrue(queue.cancel(task_id))
        queue.schedule_drain()
        time.sleep(0.2)
        task = store.get_agent_task(self.conn, task_id)
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["started_at"], "")

    def test_unavailable_agent_fails_and_queue_continues(self):
        self.specs["alpha"] = _spec("alpha", available=False, note="中转口未启动")
        alpha = self._enqueue("alpha", "不可用")
        beta = self._enqueue("beta", "还能跑")
        queue.schedule_drain()
        failed = self._wait(alpha)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("中转口未启动", failed["error"])
        self.assertEqual(self._wait(beta)["status"], "done")

    def test_recover_marks_running_failed_and_keeps_queued(self):
        stuck = self._enqueue("alpha", "残留")
        store.update_agent_task(self.conn, stuck, status="running",
                                started_at=store.now())
        waiting = self._enqueue("beta", "待续跑")
        self.assertEqual(queue.recover(self.conn), 1)
        stuck_task = store.get_agent_task(self.conn, stuck)
        self.assertEqual(stuck_task["status"], "failed")
        self.assertIn("重启", stuck_task["error"])
        self.assertEqual(store.get_agent_task(self.conn, waiting)["status"], "queued")
        queue.schedule_drain()
        self.assertEqual(self._wait(waiting)["status"], "done")


if __name__ == "__main__":
    unittest.main()
