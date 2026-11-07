# -*- coding: utf-8 -*-
"""实践经验库：三格必填、搜索、项目筛选、用到次数、归档与删除。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class PracticeApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db_path = pathlib.Path(self.tmp.name) / "learning.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig = store.connect
        self.patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig(path or self.db_path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def _create(self, **overrides):
        body = {
            "title": "codex 说完成不等于做对了",
            "scene": "让 codex 改完后端",
            "pitfall": "它回复完成，接口还是 500",
            "next_time": "先看 /api/health 和实际请求",
            "tags": "#AI协作 #部署",
            "source": "ask",
        }
        body.update(overrides)
        return self.client.post("/api/practice", json=body, headers=AUTH)

    def test_schema_has_practice_notes(self):
        conn = self._orig(self.db_path)
        self.addCleanup(conn.close)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='practice_notes'").fetchone()
        self.assertIsNotNone(row)

    def test_create_requires_three_fields(self):
        # 空格串能通过 pydantic 长度校验，但 service strip 后仍按缺格拒绝。
        response = self._create(scene="   ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("三格", response.json()["detail"])

    def test_create_and_get(self):
        created = self._create()
        self.assertEqual(created.status_code, 200, created.text)
        note = created.json()
        self.assertEqual(note["kind"], "pitfall")
        self.assertEqual(note["used_count"], 0)
        got = self.client.get(
            f"/api/practice/{note['id']}", headers=AUTH).json()
        self.assertEqual(got["title"], note["title"])

    def test_search_and_project_filter(self):
        first = self._create(project_id=7).json()
        self._create(title="部署后要重新打包", scene="部署 2.58",
                     pitfall="健康检查拿到旧版本号", next_time="先 PyInstaller",
                     project_id=8)
        found = self.client.get(
            "/api/practice?q=codex", headers=AUTH).json()
        self.assertEqual(found["count"], 1)
        self.assertEqual(found["items"][0]["id"], first["id"])
        project = self.client.get(
            "/api/practice?project_id=7", headers=AUTH).json()
        self.assertEqual(project["count"], 1)

    def test_used_archive_and_delete(self):
        note = self._create().json()
        used = self.client.post(
            f"/api/practice/{note['id']}/used", headers=AUTH).json()
        self.assertEqual(used["used_count"], 1)
        self.assertTrue(used["last_used"])
        archived = self.client.post(
            f"/api/practice/{note['id']}/archive", headers=AUTH).json()
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self.client.get(
            "/api/practice", headers=AUTH).json()["count"], 0)
        self.assertEqual(self.client.delete(
            f"/api/practice/{note['id']}", headers=AUTH).status_code, 200)

    def test_patch_updates_next_time(self):
        note = self._create().json()
        updated = self.client.patch(
            f"/api/practice/{note['id']}",
            json={"next_time": "先跑一遍全量测试"}, headers=AUTH).json()
        self.assertEqual(updated["next_time"], "先跑一遍全量测试")
        bad = self.client.patch(
            f"/api/practice/{note['id']}", json={"next_time": ""}, headers=AUTH)
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
