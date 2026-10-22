# -*- coding: utf-8 -*-
"""后台守护：退出标记与「要不要拉起」的判断（不碰真实计划任务）。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from learnsys.ask import guard, shortcuts


class GuardMarkerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_没有标记就是没退出(self):
        self.assertFalse(guard.quit_requested(self.root))

    def test_标记写上再清掉(self):
        guard.mark_quit(self.root)
        self.assertTrue(guard.quit_requested(self.root))
        self.assertTrue(guard.marker_path(self.root).exists())
        guard.clear_quit(self.root)
        self.assertFalse(guard.quit_requested(self.root))

    def test_清标记幂等(self):
        guard.clear_quit(self.root)
        guard.clear_quit(self.root)
        self.assertFalse(guard.quit_requested(self.root))

    def test_目录不存在也能写标记(self):
        root = self.root / "还没建" / "子目录"
        guard.mark_quit(root)
        self.assertTrue(guard.quit_requested(root))

    def test_要不要拉起_真值表(self):
        self.assertTrue(guard.should_start(quit_requested=False, healthy=False))
        self.assertFalse(guard.should_start(quit_requested=False, healthy=True))
        self.assertFalse(guard.should_start(quit_requested=True, healthy=False))
        self.assertFalse(guard.should_start(quit_requested=True, healthy=True))


class ProtocolTest(unittest.TestCase):
    def test_协议命令行带引号且默认后台启动(self):
        line = shortcuts.protocol_command(pathlib.Path(r"D:\学习 工作台\学习工作台.exe"))
        self.assertEqual(line, '"D:\\学习 工作台\\学习工作台.exe" --background')

    def test_协议名固定(self):
        self.assertEqual(shortcuts.PROTOCOL, "learnsys")


if __name__ == "__main__":
    unittest.main(verbosity=2)
