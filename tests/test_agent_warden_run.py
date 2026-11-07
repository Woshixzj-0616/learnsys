# -*- coding: utf-8 -*-
"""P32 端到端：fake agent 跑完后，验收结果真的落进 agent_tasks。"""
from __future__ import annotations

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


def _script(body: str = "") -> str:
    return textwrap.dedent(f"""
        import json
        {body}
        print(json.dumps({{"kind": "result", "text": "完成"}}, ensure_ascii=False), flush=True)
    """)


def _spec(agent_id: str, body: str = "") -> base.AgentSpec:
    return base.AgentSpec(
        id=agent_id, name=agent_id.title(), kind="fake", command=sys.executable,
        args=["-c", _script(body)], available=True)


class WardenRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        # 真实部署里数据目录与工作区是分开的：数据库、输出文件都不该落在 workspace 内，
        # 否则 SQLite 的 -wal/-shm 会被快照当成 agent 的改动。
        self.workspace = self.root / "工作区"
        self.workspace.mkdir()
        self.db = self.root / "learning.db"
        self.conn = store.connect(self.db)
        self.addCleanup(self.conn.close)

        patcher = mock.patch.object(
            app_config, "USER",
            {"agents": {"timeout": 30, "max_concurrent": 2, "queue_max": 10}})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(app_config, "DATA_ROOT", self.root / "数据")
        patcher.start()
        self.addCleanup(patcher.stop)
        original = store.connect
        patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: original(path or self.db))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.original_spec_for = agents.registry.spec_for
        patcher = mock.patch.object(
            agents.registry, "spec_for",
            side_effect=lambda agent_id, _s=None: self.specs.get(agent_id))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.specs: dict[str, base.AgentSpec] = {}

    def _run(self, body: str = "") -> dict:
        self.specs = {"fake": _spec("fake", body)}
        task_id = store.add_agent_queued_task(
            self.conn, agent="fake", prompt="测试任务",
            workspace=str(self.workspace))
        self.assertIsNotNone(task_id)
        queue.schedule_drain(self.db)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            task = store.get_agent_task(self.conn, task_id)
            if task and task["status"] in ("done", "failed", "cancelled"):
                return task
            time.sleep(0.05)
        self.fail("任务没有在 15 秒内结束")

    def test_read_only_no_change_passes(self):
        task = self._run()
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["verdict_state"], "passed")
        self.assertTrue(task["has_contract"])
        verdict = agents.warden.loads(
            store.get_agent_task_verdict(self.conn, task["id"]))
        self.assertEqual(verdict["state"], "passed")
        self.assertEqual(verdict["changes"]["count"], 0)

    def test_read_only_change_fails(self):
        task = self._run(
            'open("agent-写过.txt", "w", encoding="utf-8").write("改了")')
        self.assertEqual(task["status"], "done")       # 进程本身是成功的
        self.assertEqual(task["verdict_state"], "failed")   # 但验收没过
        verdict = agents.warden.loads(
            store.get_agent_task_verdict(self.conn, task["id"]))
        self.assertIn("agent-写过.txt", verdict["changes"]["changed"])

    def test_old_task_without_contract_is_skipped(self):
        # 直接插一条没有契约的老任务，验证兼容
        task_id = store.add_agent_task(
            self.conn, agent="fake", prompt="老任务",
            workspace=str(self.workspace))
        self.assertTrue(task_id)
        contract = agents.warden.normalize_contract(
            store.get_agent_task_contract(self.conn, task_id),
            "read", self.workspace)[0]
        self.assertTrue(contract["auto"])
        verdict = agents.warden.verify(None, self.workspace, None)
        self.assertEqual(verdict["state"], "skipped")


if __name__ == "__main__":
    unittest.main()
