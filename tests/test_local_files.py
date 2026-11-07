# -*- coding: utf-8 -*-
"""P34.1 本机文件工具：白名单检索、分段读取、敏感/二进制拒绝、外部确认。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config
from learnsys.agent import tools
from learnsys.agent.tools import local_files


class LocalFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.data_root = self.root / "data"
        (self.root / "网络").mkdir()
        (self.root / "下载").mkdir()
        (self.root / "node_modules" / "pkg").mkdir(parents=True)
        self.note = self.root / "网络" / "网络基础.txt"
        self.note.write_text(
            "第一章：TCP 三次握手。\n" + "第二章：拥塞控制。" * 100, encoding="utf-8")
        (self.root / "下载" / "旧笔记.md").write_text("# 旧笔记", encoding="utf-8")
        (self.root / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1;",
                                                                    encoding="utf-8")
        (self.root / ".env").write_text("SECRET=1", encoding="utf-8")
        (self.root / "设置.json").write_text('{"token": "x"}', encoding="utf-8")
        self.binary = self.root / "图片.bin"
        self.binary.write_bytes(b"\x00\x01\x02binary")
        self.patcher = mock.patch.object(
            config, "USER", {"materials": {"import_dirs": [str(self.root)]}})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        local_files._SCAN_CACHE.clear()
        local_files._TEXT_CACHE.clear()
        self.ctx = tools.ToolContext(data_root=self.data_root)

    def test_search_by_name_and_skip_noise(self):
        text = local_files.search_local_files("网络", ctx=self.ctx)
        self.assertIn("网络基础.txt", text)
        self.assertNotIn("index.js", text)
        self.assertNotIn("设置.json", text)
        self.assertNotIn(".env", text)

    def test_search_empty_query_returns_recent(self):
        text = local_files.search_local_files("", limit=5, ctx=self.ctx)
        self.assertIn("网络基础.txt", text)

    def test_read_text_in_chunks(self):
        first = local_files.read_local_file(str(self.note), 0, 500, ctx=self.ctx)
        self.assertIn("网络基础.txt", first)
        self.assertIn("TCP 三次握手", first)
        self.assertIn("offset=500", first)
        rest = local_files.read_local_file(str(self.note), 500, 500, ctx=self.ctx)
        self.assertIn("第二章", rest)

    def test_sensitive_files_never_read(self):
        for name in ("设置.json", ".env"):
            text = local_files.read_local_file(str(self.root / name), ctx=self.ctx)
            self.assertIn("不读", text)
            self.assertNotIn("token", text)
            self.assertNotIn("SECRET", text)

    def test_windows_name_tricks_blocked(self):
        self.assertIsNone(local_files.resolve_path(str(self.root / "网络基础.txt:secret")))
        text = local_files.read_local_file(str(self.root / "设置.json "), ctx=self.ctx)
        self.assertIn("不读", text)

    def test_binary_refused(self):
        text = local_files.read_local_file(str(self.binary), ctx=self.ctx)
        self.assertIn("二进制", text)

    def test_outside_root_needs_confirmation(self):
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside = pathlib.Path(outside_dir.name) / "白名单外.txt"
        outside.write_text("外部内容", encoding="utf-8")
        denied = local_files.read_local_file(str(outside), ctx=self.ctx)
        self.assertIn("不在「本机可读目录」里", denied)
        self.assertNotIn("外部内容", denied)
        self.assertTrue(tools.needs_confirm("read_local_file", {"path": str(outside)}))
        self.ctx.approved_paths.add(str(outside.resolve()))
        self.assertFalse(tools.needs_confirm(
            "read_local_file", {"path": str(outside)}, self.ctx))
        allowed = local_files.read_local_file(str(outside), ctx=self.ctx)
        self.assertIn("外部内容", allowed)

    def test_inside_root_needs_no_confirmation(self):
        self.assertFalse(tools.needs_confirm("read_local_file", {"path": str(self.note)}))
        self.assertTrue(tools.needs_confirm("write_study_file",
                                            {"relative_path": "日志.md"}))

    def test_surface_only_workbench_ask(self):
        def names(**kwargs):
            return {item["name"] for item in tools.schemas_for(**kwargs)}
        ask = names(mode="explain", surface="ask")
        self.assertIn("search_local_files", ask)
        self.assertIn("read_local_file", ask)
        for surface in ("quickbar", "cet6", "video"):
            cut = names(mode="explain", surface=surface)
            self.assertNotIn("search_local_files", cut)
            self.assertNotIn("read_local_file", cut)
        self.assertNotIn("search_local_files", names(mode="quiz", surface="ask"))

    def test_execute_dispatch(self):
        text, preview, ok = tools.execute(
            "search_local_files", {"query": "网络"}, self.ctx)
        self.assertTrue(ok)
        self.assertIn("网络基础.txt", text)
        self.assertEqual(preview, "搜了本机文件")
        text, preview, ok = tools.execute(
            "read_local_file", {"path": str(self.note), "length": 500}, self.ctx)
        self.assertTrue(ok)
        self.assertIn("TCP 三次握手", text)

    def test_read_writes_audit_log(self):
        local_files.read_local_file(str(self.note), ctx=self.ctx)
        log = self.data_root / "日志" / "本机文件读取.jsonl"
        self.assertTrue(log.exists())
        self.assertIn("网络基础.txt", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
