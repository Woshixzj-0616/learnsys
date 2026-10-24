"""学习工作台窗口外壳：浏览器选择、窗口枚举、打开失败退回默认浏览器。"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from learnsys.ask import workbench
from learnsys.core import browsers


class WorkbenchTest(unittest.TestCase):
    def test_env_browser_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "mybrowser.exe"
            fake.write_bytes(b"MZ")
            with mock.patch.dict(os.environ, {"LEARNSYS_BROWSER": str(fake)}):
                self.assertEqual(browsers.find_browser(), str(fake))

    def test_missing_browser_falls_back(self):
        with mock.patch.object(workbench, "find_browser", return_value=None), \
                mock.patch.object(workbench.webbrowser, "open") as opened:
            how = workbench.open_app_window("http://127.0.0.1:8765/")
        self.assertEqual(how, "默认浏览器")
        opened.assert_called_once_with("http://127.0.0.1:8765/")

    def test_open_uses_app_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp) / "msedge.exe"
            fake.write_bytes(b"MZ")
            with mock.patch.object(workbench, "find_browser", return_value=str(fake)), \
                    mock.patch.object(workbench.subprocess, "Popen") as popen:
                how = workbench.open_app_window("http://127.0.0.1:8765/#/today",
                                                size=(1200, 800))
        args = popen.call_args.args[0]
        self.assertEqual(how, "msedge.exe")
        self.assertIn("--app=http://127.0.0.1:8765/#/today", args)
        self.assertIn("--window-size=1200,800", args)

    def test_window_enumeration_does_not_throw(self):
        # 没有对应窗口时返回 False；有窗口时由真实启动流程覆盖（见 P3 验收记录）
        self.assertIsInstance(workbench._windows_matching(), list)
        self.assertIsInstance(workbench.focus_window("· 绝对不存在的标题"), bool)


if __name__ == "__main__":
    unittest.main()
