# -*- coding: utf-8 -*-
"""T4.1：六级精听静态挂载。

锁四件事：
① 工作台 HTML、试卷索引、data.js、audio.mp3 全部 200；
② `/cet6` 直接跳到工作台，`/cet6/` 同样；
③ 只暴露「工作台 / 试卷」两个子目录，根目录里的 .py / 原始音频不进浏览器；
④ 模块没装时返回中文 404，不影响其他接口。
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import urllib.parse
from unittest import mock

from fastapi.testclient import TestClient

from learnsys import config
from learnsys.server.app import create_app

TOKEN = "test-token"
PAPER = "2016年06月大学英语6级听力（卷一）"


class Cet6StaticTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "工作台").mkdir()
        (self.root / "工作台" / "精听工作台.html").write_text(
            "<!doctype html><title>精听工作台</title>", encoding="utf-8")
        (self.root / "工作台" / "启动分析服务.bat").write_text("pause", encoding="utf-8")
        papers = self.root / "试卷" / PAPER
        papers.mkdir(parents=True)
        (self.root / "试卷" / "试卷索引.js").write_text(
            "window.PAPERS = [%r];" % PAPER, encoding="utf-8")
        (papers / "data.js").write_text("window.DATA = {};", encoding="utf-8")
        (papers / "audio.mp3").write_bytes(b"ID3fake-audio")
        (self.root / "_批量worker.py").write_text("print('不该被看到')", encoding="utf-8")

        self.patcher = mock.patch.object(config, "cet6_dir", return_value=self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(create_app(token=TOKEN))

    def test_workbench_and_assets_200(self):
        entry = f"/cet6/工作台/精听工作台.html"
        res = self.client.get(urllib.parse.quote(entry, safe="/"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("精听工作台", res.text)

        index = self.client.get(urllib.parse.quote("/cet6/试卷/试卷索引.js", safe="/"))
        self.assertEqual(index.status_code, 200)
        self.assertIn("PAPERS", index.text)

        data = urllib.parse.quote(f"/cet6/试卷/{PAPER}/data.js", safe="/")
        self.assertEqual(self.client.get(data).status_code, 200)

        audio = urllib.parse.quote(f"/cet6/试卷/{PAPER}/audio.mp3", safe="/")
        res = self.client.get(audio)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"ID3fake-audio")

    def test_cet6_root_redirects_to_workbench(self):
        for path in ("/cet6", "/cet6/"):
            res = self.client.get(path, follow_redirects=False)
            self.assertIn(res.status_code, (307, 308), path)
            target = urllib.parse.unquote(res.headers["location"])
            self.assertEqual(target, "/cet6/工作台/精听工作台.html")
            self.assertEqual(self.client.get(res.headers["location"]).status_code, 200)

    def test_only_workbench_and_papers_exposed(self):
        res = self.client.get("/cet6/_%E6%89%B9%E9%87%8Fworker.py")
        self.assertEqual(res.status_code, 404, "根目录里的脚本不许被静态服务暴露")
        self.assertEqual(self.client.get("/cet6/试卷/../_批量worker.py").status_code, 404)
        bat = urllib.parse.quote("/cet6/工作台/启动分析服务.bat", safe="/")
        self.assertEqual(self.client.get(bat).status_code, 404,
                         "工作台目录里的批处理不许被静态服务暴露")

    def test_missing_module_returns_chinese_404(self):
        with mock.patch.object(config, "cet6_dir", return_value=self.root / "不存在"):
            client = TestClient(create_app(token=TOKEN))
            res = client.get("/cet6")
            self.assertEqual(res.status_code, 404)
            self.assertIn("还没装六级精听模块", res.text)
            self.assertIn("text/html", res.headers.get("content-type", ""))
            # 主功能不受影响
            self.assertEqual(client.get("/api/health").status_code, 200)


class RegistryTest(unittest.TestCase):
    def test_cet6_module_is_ready(self):
        from learnsys.modules import load_registry
        data = load_registry()
        mod = next(m for m in data["modules"] if m["id"] == "cet6")
        self.assertEqual(mod["status"], "ready")
        # P24 起外层是四标签原生页；精听 iframe 在 tabs 里，不再作为插件 entry
        self.assertEqual(mod["type"], "native-page")
        self.assertEqual(mod["entry"], "pages/cet6.html")
        self.assertIn("cet6/index.js", mod["script"])

    def test_iframe_branch_does_not_fetch_web_page(self):
        """iframe 的 entry 是 /cet6/…，不能先去 /web/cet6/… 拿页面（真踩过 404）。"""
        from learnsys.modules import web_dir
        source = (web_dir() / "js" / "shell.js").read_text(encoding="utf-8")
        self.assertLess(source.index('module.type === "iframe"'),
                        source.index("await fetchPage(module)"),
                        "iframe 分支必须放在 fetchPage 之前")


if __name__ == "__main__":
    unittest.main(verbosity=2)
