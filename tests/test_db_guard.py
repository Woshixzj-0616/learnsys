# -*- coding: utf-8 -*-
"""测试进程禁止连接生产库：守门规则本身也要有测试。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys.core.db import connection


class ProductionDbGuardTest(unittest.TestCase):
    def test_real_db_path_is_blocked(self):
        """测试进程里直接连真实库必须报错，而不是悄悄迁移。"""
        with self.assertRaises(RuntimeError) as ctx:
            connection.connect(connection._REAL_DB_PATH)
        self.assertIn("禁止连接生产库", str(ctx.exception))

    def test_temp_db_path_is_allowed(self):
        """临时库不受影响，正常建表可用。"""
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        target = pathlib.Path(tmp.name) / "learning.db"
        conn = connection.connect(target)
        try:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                connection.SCHEMA_VERSION)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
