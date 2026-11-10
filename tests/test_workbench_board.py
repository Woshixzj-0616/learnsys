# -*- coding: utf-8 -*-
"""今日页聚合：三个接口的装配收成一份，今日目标只算一次。"""
from __future__ import annotations

import unittest
from unittest import mock

from learnsys import store
from learnsys.services import day_plan
from learnsys.services import workbench


class WorkbenchBoardTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_board_shares_one_plan(self):
        with mock.patch.object(day_plan, "build", wraps=day_plan.build) as build:
            data = workbench.payload(self.conn)
        self.assertEqual(build.call_count, 1, "今日目标只应算一次")
        self.assertEqual(set(data), {"date", "overview", "today", "home"})
        tasks = data["overview"]["today"]["goal_tasks"]
        self.assertEqual(data["home"]["learning"]["tasks"], tasks)
        self.assertEqual(data["home"]["learning"]["href"],
                         tasks[1]["href"],
                         "学习域入口必须跟训练格主推一致")
        self.assertIn("actions", data["today"])
        self.assertIn("coaching", data["today"])

    def test_empty_database_still_has_shape(self):
        data = workbench.payload(self.conn)
        self.assertEqual(data["overview"]["today"]["goal_total"], 3)
        self.assertEqual(data["home"]["learning"]["done"], 0)
        self.assertEqual(data["today"]["due_reviews"], 0)


if __name__ == "__main__":
    unittest.main()
