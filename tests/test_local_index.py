# -*- coding: utf-8 -*-
"""P34.2 本机目录索引：增量同步、标记清除、敏感排除、搜索排序、根变化。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys import config, store
from learnsys.services import local_index


class LocalIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.root = self.base / "资料"
        (self.root / "子目录").mkdir(parents=True)
        (self.root / "node_modules" / "pkg").mkdir(parents=True)

        self.note = self.root / "网络基础.txt"
        self.note.write_text("第一章 TCP 三次握手", encoding="utf-8")
        (self.root / "子目录" / "网络实验.md").write_text("# 实验", encoding="utf-8")
        (self.root / "报告.pdf").write_bytes(b"%PDF-1.4 test")
        (self.root / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=1", encoding="utf-8")
        (self.root / "设置.json").write_text("{}", encoding="utf-8")

        self.patcher = mock.patch.object(
            config, "USER", {"materials": {"import_dirs": [str(self.root)]}})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.db_path = self.base / "test.db"
        conn = store.connect(self.db_path)
        conn.close()
        self._orig_connect = store.connect
        self.connect_patcher = mock.patch.object(
            store, "connect",
            side_effect=lambda path=None: self._orig_connect(path or self.db_path))
        self.connect_patcher.start()
        self.addCleanup(self.connect_patcher.stop)

        local_index.reconcile(self.root)

    def _rows(self):
        conn = store.connect()
        try:
            return conn.execute(
                "SELECT path FROM local_files ORDER BY path").fetchall()
        finally:
            conn.close()

    def _status(self, root=None):
        conn = store.connect()
        try:
            return store.local_file_root_status(conn, str(root or self.root))
        finally:
            conn.close()

    def test_indexes_files_and_skips_noise(self):
        paths = {row[0] for row in self._rows()}
        self.assertIn(str(self.note), paths)
        self.assertIn(str(self.root / "子目录" / "网络实验.md"), paths)
        self.assertIn(str(self.root / "报告.pdf"), paths)
        self.assertNotIn(str(self.root / "node_modules" / "pkg" / "index.js"), paths)
        self.assertNotIn(str(self.root / ".env"), paths)
        self.assertNotIn(str(self.root / "设置.json"), paths)
        status = self._status()
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["file_count"], 3)

    def test_search_orders_and_filters(self):
        hit = local_index.search("网络")
        names = [pathlib.Path(row[0]).name for row in hit["entries"]]
        self.assertIn("网络基础.txt", names)
        self.assertIn("网络实验.md", names)
        self.assertEqual(hit["matched"], 2)

        exact = local_index.search("网络基础.txt")
        self.assertEqual(pathlib.Path(exact["entries"][0][0]).name, "网络基础.txt")

        by_path = local_index.search("子目录")
        self.assertEqual([pathlib.Path(row[0]).name for row in by_path["entries"]],
                         ["网络实验.md"])

        only_pdf = local_index.search("", suffix="pdf")
        self.assertEqual([pathlib.Path(row[0]).name for row in only_pdf["entries"]],
                         ["报告.pdf"])

    def test_incremental_add_modify_delete(self):
        added = self.root / "新笔记.md"
        added.write_text("新内容", encoding="utf-8")
        local_index.reconcile(self.root)
        self.assertIn(str(added), {row[0] for row in self._rows()})

        self.note.unlink()
        local_index.reconcile(self.root)
        self.assertNotIn(str(self.note), {row[0] for row in self._rows()})

        old = self.root / "子目录" / "网络实验.md"
        new = self.root / "子目录" / "网络实验-改名.md"
        old.rename(new)
        local_index.reconcile(self.root)
        paths = {row[0] for row in self._rows()}
        self.assertNotIn(str(old), paths)
        self.assertIn(str(new), paths)

    def test_removed_root_is_cleared_by_tick(self):
        other = self.base / "另一个"
        other.mkdir()
        config.USER["materials"]["import_dirs"] = [str(other)]
        local_index.tick()
        self.assertEqual(self._rows(), [])
        self.assertIsNone(self._status())

    def test_truncated_scan_does_not_delete_unseen(self):
        # 先完整索引；再加两个新文件、删掉 note、把上限压到 2：
        # 截断的扫描不得删除没扫到的旧行（否则会误删 note 之外的文件）
        (self.root / "新增一.md").write_text("a", encoding="utf-8")
        (self.root / "新增二.md").write_text("b", encoding="utf-8")
        self.note.unlink()
        with mock.patch.object(local_index, "MAX_INDEX_ENTRIES", 2):
            status = local_index.reconcile(self.root)
        self.assertEqual(status["status"], "truncated")
        self.assertIn(str(self.note), {row[0] for row in self._rows()})

    def test_missing_root_keeps_rows(self):
        status = local_index.reconcile(self.base / "不存在")
        self.assertEqual(status["status"], "missing")
        self.assertTrue(self._rows())

    def test_status_returns_pending_for_unscanned_root(self):
        pending = self.base / "待扫"
        pending.mkdir()
        config.USER["materials"]["import_dirs"] = [str(self.root), str(pending)]
        data = local_index.status()
        by_root = {row["root"]: row for row in data["roots"]}
        self.assertEqual(by_root[str(pending)]["status"], "pending")
        self.assertEqual(by_root[str(self.root)]["file_count"], 3)


if __name__ == "__main__":
    unittest.main()
