# -*- coding: utf-8 -*-
"""P30.3 创作库接口：作品/预设、导入、图片回显与路径校验。"""
from __future__ import annotations

import base64
import pathlib
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config as app_config
from learnsys import store
from learnsys.server import app as server_app

TOKEN = "art-test-token"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAF"
    "gwJ/h30l5QAAAABJRU5ErkJggg==")


class TestArtRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.data_root = self.root / "data"
        self.data_root.mkdir()
        self.db = self.root / "learning.db"
        store.connect(self.db).close()
        self.orig = store.connect
        patches = [
            mock.patch.object(
                store, "connect",
                side_effect=lambda path=None: self.orig(path or self.db)),
            mock.patch.object(app_config, "DATA_ROOT", self.data_root),
            mock.patch.object(app_config, "SETTINGS_FILE", self.root / "设置.json"),
            mock.patch.object(app_config, "USER", {}),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server_app.create_app(token=TOKEN))
        self.headers = {"X-Learnsys-Token": TOKEN}
        image = self.data_root / "截图" / "测试.png"
        image.parent.mkdir()
        image.write_bytes(PNG)
        self.image = image

    def _preset(self, name="霓虹赛博", **extra):
        data = {"name": name, "prompt": "霓虹灯、雨夜", "negative": "模糊"}
        data.update(extra)
        response = self.client.post("/api/art/presets", headers=self.headers,
                                    json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _work(self, **payload):
        data = {"title": "霓虹城市", "prompt": "赛博朋克街道",
                "model": "豆包"}
        data.update(payload)
        response = self.client.post("/api/art/works", headers=self.headers,
                                    json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_work_and_preset_lifecycle(self):
        preset = self._preset()
        work = self._work(preset_id=preset["id"])
        self.assertEqual(work["preset_id"], preset["id"])
        listed = self.client.get("/api/art/works", headers=self.headers).json()
        self.assertEqual(listed["count"], 1)
        archived = self.client.post(f"/api/art/works/{work['id']}/archive",
                                    headers=self.headers)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(
            self.client.get("/api/art/works", headers=self.headers)
            .json()["count"], 0)
        restored = self.client.post(f"/api/art/works/{work['id']}/restore",
                                    headers=self.headers)
        self.assertEqual(restored.json()["status"], "active")
        patched = self.client.patch(f"/api/art/works/{work['id']}",
                                    headers=self.headers,
                                    json={"title": "霓虹城市 2"})
        self.assertEqual(patched.json()["title"], "霓虹城市 2")
        self.assertEqual(
            self.client.delete(f"/api/art/presets/{preset['id']}",
                               headers=self.headers).status_code, 200)
        detail = self.client.get(f"/api/art/works/{work['id']}",
                                 headers=self.headers).json()
        self.assertEqual(detail["preset_id"], 0)
        self.assertEqual(
            self.client.delete(f"/api/art/works/{work['id']}",
                               headers=self.headers).status_code, 200)

    def test_validation(self):
        empty = self.client.post("/api/art/works", headers=self.headers,
                                 json={"title": ""})
        self.assertEqual(empty.status_code, 400)
        self.assertIn("标题", empty.json()["detail"])
        bad = self.client.post("/api/art/works", headers=self.headers,
                               json={"title": "x",
                                     "file_path": str(self.root / "outside.png")})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("上传", bad.json()["detail"])
        self.assertEqual(
            self.client.get("/api/art/works/99999",
                            headers=self.headers).status_code, 404)

    def test_image_is_served_from_data_root(self):
        work = self._work(file_path=str(self.image))
        self.assertTrue(work["file_path"].endswith("测试.png"))
        response = self.client.get(f"/media/art/{work['id']}/image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG)

    def test_import_text(self):
        text = ("标题：霓虹城市\n提示词：赛博朋克街道\n风格：霓虹赛博\n模型：豆包\n\n"
                "标题：海边\n提示词：蓝色海面")
        response = self.client.post("/api/art/import", headers=self.headers,
                                    json={"text": text})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(self.client.get("/api/art/works",
                                             headers=self.headers).json()["items"]), 2)
        self.assertEqual(len(self.client.get("/api/art/presets",
                                             headers=self.headers).json()["items"]), 1)
        empty = self.client.post("/api/art/import", headers=self.headers,
                                 json={"text": "  "})
        self.assertEqual(empty.status_code, 400)

    def test_requires_token(self):
        self.assertEqual(self.client.get("/api/art/works").status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
