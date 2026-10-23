# -*- coding: utf-8 -*-
"""六级双写审计：整卷比对、写后校验、空快照保护、状态读取。

先写测试再实现（P17.1）。判据与口径见 docs/施工单/P17.1-六级双写退休.md。
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"


def sentence(i=1, **kw):
    base = {"sentence": i, "en": "hello", "tags": [], "note": "", "loops": 0, "plays": 0}
    base.update(kw)
    return base


def paper_payload(items, *, hydration="local", done=None, paper_sig="sig-1"):
    return {
        "paper": "测试卷", "paper_id": "p1",
        "items": items, "hydration": hydration, "mode": "http",
        "paper_sig": paper_sig, "client_ts": "2026-10-23T08:00:00",
        "client_day": "2026-10-23", "push_failed": 0,
    }


def item(section="Section A", title="C1", sentences=None, done=None):
    return {"section": section, "item": title,
            "sentences": sentences or [sentence()], "done": done or []}


class DualWriteRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        store.connect(self.db_path).close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    # ---- GET /api/cet6/state ----
    def test_state_empty_is_ok(self):
        res = self.client.get("/api/cet6/state", params={"paper_id": "p1"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["items"], [])
        self.assertEqual(data["count"], 0)

    def test_state_groups_and_splits_tags(self):
        conn = store.connect()
        self.addCleanup(conn.close)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[sentence(1, tags=["生词", "连读"], note="n")], done=[1])
        data = self.client.get("/api/cet6/state", params={"paper_id": "p1"}).json()
        self.assertEqual(data["count"], 1)
        got = data["items"][0]["sentences"][0]
        self.assertEqual(got["tags"], ["生词", "连读"])
        self.assertTrue(got["done"])
        self.assertEqual(got["note"], "n")

    # ---- POST /api/cet6/sync-paper ----
    def test_sync_paper_identical_is_clean(self):
        conn = store.connect()
        self.addCleanup(conn.close)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[sentence(1, tags=["生词"], note="n", loops=2, plays=3)],
            done=[1])
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(1, tags=["生词"], note="n", loops=2, plays=3)],
                  done=[1])]))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["compared"], 1)
        self.assertEqual(data["diff_fields"], 0)
        self.assertEqual(data["missing_db"], 0)
        self.assertTrue(data["post_ok"])
        self.assertEqual(data["run_id"], 1)

    def test_sync_paper_records_field_diff_and_writes(self):
        conn = store.connect()
        self.addCleanup(conn.close)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[sentence(1, tags=["生词"], note="旧", loops=1, plays=1)],
            done=[1])
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(1, tags=["连读"], note="新", loops=2, plays=2)],
                  done=[])]))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "diff")
        self.assertGreaterEqual(data["diff_fields"], 3)   # done / tags / note / loops
        self.assertEqual(data["minor_fields"], 1)         # plays 单独归 minor
        self.assertTrue(data["post_ok"])
        got = store.cet6_progress_item(conn, paper_id="p1", section="Section A", item="C1")[0]
        self.assertFalse(got["done"])
        self.assertEqual(got["tags"], ["连读"])
        self.assertEqual(got["note"], "新")
        self.assertEqual(got["loops"], 2)

    def test_blocked_empty_does_not_wipe_server(self):
        conn = store.connect()
        self.addCleanup(conn.close)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[sentence(1)], done=[1])
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(1)], done=[])], hydration="local"))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"]["status"], "blocked_empty")
        got = store.cet6_progress_item(conn, paper_id="p1", section="Section A", item="C1")[0]
        self.assertTrue(got["done"])
        runs = conn.execute("SELECT status FROM cet6_dualwrite_runs").fetchall()
        self.assertEqual([r[0] for r in runs], ["blocked_empty"])

    def test_empty_paper_with_empty_server_is_allowed(self):
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(1)], done=[])]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_missing_and_orphan_rows_are_counted(self):
        conn = store.connect()
        self.addCleanup(conn.close)
        store.upsert_cet6_progress(
            conn, paper_id="p1", paper_title="测试卷", section="Section A",
            item="C1", rows=[sentence(1)], done=[1])
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(2)], done=[2])]))
        data = res.json()
        self.assertEqual(data["status"], "diff")
        self.assertEqual(data["missing_db"], 1)
        self.assertEqual(data["orphan_db"], 1)

    def test_long_note_is_invalid_and_truncated(self):
        long_note = "字" * 1200
        res = self.client.post("/api/cet6/sync-paper", json=paper_payload(
            [item(sentences=[sentence(1, note=long_note)], done=[1])]))
        data = res.json()
        self.assertEqual(data["invalid"], 1)
        conn = store.connect()
        self.addCleanup(conn.close)
        got = store.cet6_progress_item(conn, paper_id="p1", section="Section A", item="C1")[0]
        self.assertEqual(len(got["note"]), 1000)

    def test_missing_paper_id_is_400(self):
        payload = paper_payload([item()])
        payload["paper_id"] = ""
        res = self.client.post("/api/cet6/sync-paper", json=payload)
        self.assertEqual(res.status_code, 400)

    def test_state_route_needs_no_token_but_context_does(self):
        self.assertEqual(
            self.client.get("/api/cet6/state", params={"paper_id": "p1"}).status_code, 200)
        self.assertEqual(
            self.client.get("/api/cet6/context", params={"paper_id": "p1"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
