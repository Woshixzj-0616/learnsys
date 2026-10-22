# -*- coding: utf-8 -*-
"""资料库批量导入：白名单、去重、Obsidian 只读。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server.app import create_app

TOKEN = "test-token"
AUTH = {"X-Learnsys-Token": TOKEN}


class MaterialsImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.course = self.root / "课程"
        self.course.mkdir()
        (self.course / "第一章.md").write_text(
            "计算机网络的分层模型分为应用层、传输层、网络层和链路层。", encoding="utf-8")
        (self.course / "第二章.txt").write_text(
            "路由选择协议包括 RIP、OSPF 和 BGP，各自适用的网络规模不同。", encoding="utf-8")
        (self.course / "重复.md").write_text(
            "计算机网络的分层模型分为应用层、传输层、网络层和链路层。", encoding="utf-8")
        (self.course / "旧格式.doc").write_text("Word 97", encoding="utf-8")

        self.obsidian = self.root / "笔记库"
        self.obsidian.mkdir()
        (self.obsidian / "复习.md").write_text(
            "TCP 三次握手：SYN、SYN-ACK、ACK，建立可靠连接。", encoding="utf-8")

        self.db_path = self.data / "learning.db"
        store.connect(self.db_path).close()
        self._orig_connect = store.connect
        self.connect_patch = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig_connect(path or self.db_path))
        self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.root_patch = mock.patch.object(app_config, "DATA_ROOT", self.data)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def _settings(self, **materials):
        patcher = mock.patch.dict(app_config.USER, {"materials": materials}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_import_dir_skips_duplicates(self):
        self._settings(import_dirs=[str(self.course)])
        response = self.client.post(
            "/api/materials/import-dir",
            json={"path": str(self.course), "course": "计算机网络"}, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["imported"], 2)
        self.assertEqual(body["skipped"], 1)
        self.assertEqual(body["failed"], 0)
        conn = store.connect(self.db_path)
        try:
            items = store.list_materials(conn, limit=10)
        finally:
            conn.close()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["course"] == "计算机网络" for item in items))

    def test_directory_outside_whitelist_is_rejected(self):
        self._settings(import_dirs=[str(self.root / "别的目录")])
        response = self.client.post(
            "/api/materials/import-dir",
            json={"path": str(self.course)}, headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertIn("允许", response.json()["detail"])

    def test_empty_whitelist_tells_user_where_to_configure(self):
        self._settings(import_dirs=[])
        response = self.client.post(
            "/api/materials/import-dir",
            json={"path": str(self.course)}, headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertIn("设置", response.json()["detail"])

    def test_obsidian_requires_configured_dir(self):
        self._settings(import_dirs=[str(self.course)], obsidian_dir="")
        response = self.client.post(
            "/api/materials/import-dir",
            json={"path": str(self.obsidian), "source": "obsidian"}, headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Obsidian", response.json()["detail"])

    def test_obsidian_imports_only_markdown(self):
        (self.obsidian / "附件.pdf").write_bytes(b"not a real pdf")
        self._settings(import_dirs=[], obsidian_dir=str(self.obsidian))
        response = self.client.post(
            "/api/materials/import-dir",
            json={"path": str(self.obsidian), "source": "obsidian"}, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["imported"], 1)
        conn = store.connect(self.db_path)
        try:
            items = store.list_materials(conn, limit=10)
        finally:
            conn.close()
        self.assertEqual([item["title"] for item in items], ["复习.md"])
        self.assertEqual(items[0]["source"], "obsidian")


if __name__ == "__main__":
    unittest.main()
