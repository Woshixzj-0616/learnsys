# -*- coding: utf-8 -*-
"""P29.1 项目卡片：部分更新、重名、归档与默认列表口径。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server import app as server_app

TOKEN = "projects-test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class ProjectsRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.db = root / "learning.db"
        store.connect(self.db).close()
        self.orig = store.connect
        patches = [
            mock.patch.object(
                store, "connect",
                side_effect=lambda path=None: self.orig(path or self.db)),
            mock.patch.object(app_config, "DATA_ROOT", root / "data"),
            mock.patch.object(app_config, "SETTINGS_FILE", root / "设置.json"),
            mock.patch.object(app_config, "USER", {}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server_app.create_app(token=TOKEN))

    def create(self, name: str, **extra):
        body = {"name": name, "repo_path": r"D:\Desktop\learnsys", **extra}
        return self.client.post("/api/projects", headers=AUTH, json=body)

    def test_patch_requires_token(self):
        created = self.create("甲项目").json()
        resp = self.client.patch(f"/api/projects/{created['id']}",
                                 json={"next_step": "换接口"})
        self.assertEqual(resp.status_code, 403)

    def test_patch_updates_only_given_fields(self):
        created = self.create("甲项目", risk="依赖 Windows").json()
        resp = self.client.patch(
            f"/api/projects/{created['id']}", headers=AUTH,
            json={"next_step": "补 P29.2"})
        self.assertEqual(resp.status_code, 200)
        item = resp.json()
        self.assertEqual(item["next_step"], "补 P29.2")
        self.assertEqual(item["name"], "甲项目")
        self.assertEqual(item["repo_path"], r"D:\Desktop\learnsys")
        self.assertEqual(item["risk"], "依赖 Windows")

    def test_patch_duplicate_name_rejected(self):
        first = self.create("甲项目").json()
        self.create("乙项目")
        resp = self.client.patch(f"/api/projects/{first['id']}", headers=AUTH,
                                 json={"name": "乙项目"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("已经存在", resp.json()["detail"])

    def test_patch_blank_name_rejected(self):
        created = self.create("甲项目").json()
        resp = self.client.patch(f"/api/projects/{created['id']}", headers=AUTH,
                                 json={"name": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_patch_bad_status_rejected(self):
        created = self.create("甲项目").json()
        resp = self.client.patch(f"/api/projects/{created['id']}", headers=AUTH,
                                 json={"status": "done"})
        self.assertEqual(resp.status_code, 400)

    def test_patch_missing_project_404(self):
        resp = self.client.patch("/api/projects/9999", headers=AUTH,
                                 json={"next_step": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_archive_hides_from_default_list(self):
        created = self.create("甲项目").json()
        self.create("乙项目")
        archived = self.client.post(
            f"/api/projects/{created['id']}/archive", headers=AUTH)
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["status"], "archived")

        default = self.client.get("/api/projects", headers=AUTH).json()
        self.assertEqual([item["name"] for item in default["items"]], ["乙项目"])
        everything = self.client.get("/api/projects?status=all",
                                     headers=AUTH).json()
        self.assertEqual(everything["count"], 2)


if __name__ == "__main__":
    unittest.main()
