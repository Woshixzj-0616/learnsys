# -*- coding: utf-8 -*-
"""第五轮边角修复的回归测试（#37–#39）。

跑法：.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learnsys import record, store  # noqa: E402
from learnsys.ask import app as app_mod, backend  # noqa: E402


class TestCrossMidnightConnection(unittest.TestCase):
    """#37 跨零点换库不许 close 旧连接（record 还要 end_session）。"""

    def test_conn_switch_does_not_close_old(self):
        a = app_mod.AskApp.__new__(app_mod.AskApp)
        a.conn = None
        a._conn_path = None

        with mock.patch.object(app_mod.config, "db_path") as db, \
             mock.patch.object(app_mod.store, "connect") as connect:
            db.side_effect = ["day1.db", "day2.db"]
            conn1 = mock.MagicMock(name="conn1")
            conn2 = mock.MagicMock(name="conn2")
            connect.side_effect = [conn1, conn2]

            got1 = a._conn()
            self.assertIs(got1, conn1)
            got2 = a._conn()          # 换库
            self.assertIs(got2, conn2)
            conn1.close.assert_not_called()   # 旧连接别 close

    def test_record_stop_survives_dead_conn(self):
        rec = record.WindowRecorder(lambda: store.connect(":memory:"))
        rec._session_id = 1
        rec._conn = mock.MagicMock()
        rec._conn.execute.side_effect = RuntimeError("database is closed")
        # 不该抛
        summary = rec.stop()
        self.assertEqual(summary, {})


class TestAbortBeforeConnect(unittest.TestCase):
    """#38 abort 已置位时连都别连。"""

    def test_no_open_when_abort_preset(self):
        import threading

        abort = threading.Event()
        abort.set()
        with mock.patch.object(backend, "_open") as opener:
            got = list(backend.ask_stream(None, "问", None, abort=abort))
        self.assertEqual(got, [])
        opener.assert_not_called()


class TestStoreMemoryConnect(unittest.TestCase):
    """#39 :memory: 连接不该去 mkdir 当成路径。"""

    def test_memory_connect_works(self):
        conn = store.connect(":memory:")
        sid = store.start_session(conn)
        self.assertGreater(sid, 0)
        store.add_ask(conn, "问", "答", 100, "m", kind="text")
        rows = store.recent_asks(conn, limit=5)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
