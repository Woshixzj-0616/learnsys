# -*- coding: utf-8 -*-
"""PWA：清单、Service Worker、图标与缓存清单的静态检查。"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from fastapi.testclient import TestClient

from learnsys.modules import web_dir
from learnsys.server.app import create_app

TOKEN = "test-token"


class PwaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(token=TOKEN))

    def test_manifest_served_with_correct_mime(self):
        res = self.client.get("/manifest.webmanifest")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/manifest+json", res.headers.get("content-type", ""))
        data = res.json()
        self.assertEqual(data["name"], "学习系统")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

    def test_service_worker_served_at_root_scope(self):
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("javascript", res.headers.get("content-type", ""))
        self.assertEqual(res.headers.get("service-worker-allowed"), "/")
        self.assertIn('startsWith("/api/")', res.text)
        self.assertIn('startsWith("/cet6/")', res.text)

    def test_precache_list_files_exist(self):
        source = (web_dir() / "sw.js").read_text(encoding="utf-8")
        paths = re.findall(r'^  "(/web/[^"]+)"', source, flags=re.M)
        self.assertGreaterEqual(len(paths), 20)
        missing = [p for p in paths if not (web_dir().parent / p.lstrip("/")).exists()]
        self.assertEqual(missing, [], f"Service Worker 预缓存里有不存在的文件：{missing}")

    def test_index_links_manifest_and_shell_registers_worker(self):
        index = (web_dir() / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest"', index)
        self.assertIn("/manifest.webmanifest", index)
        self.assertIn('id="ui-install"', index)
        shell = (web_dir() / "js" / "shell.js").read_text(encoding="utf-8")
        self.assertIn('navigator.serviceWorker.register("/sw.js"', shell)
        self.assertIn("beforeinstallprompt", shell)

    def test_icons_exist(self):
        for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png",
                     "apple-touch-icon.png"):
            path = web_dir() / "icons" / name
            self.assertTrue(path.exists(), name)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
