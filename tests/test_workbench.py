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

    def test_浏览器进程判定(self):
        # 标题相同，身份不同：Qt 窗口 / 打包 exe 都不能被当成 Web 工作台窗口
        self.assertTrue(workbench.is_browser_process(r"C:\Program Files\Edge\msedge.exe"))
        self.assertTrue(workbench.is_browser_process("MSEDGE.EXE"))
        self.assertTrue(workbench.is_browser_process("chrome.exe"))
        self.assertTrue(workbench.is_browser_process("firefox.exe"))
        self.assertFalse(workbench.is_browser_process("学习工作台.exe"))
        self.assertFalse(workbench.is_browser_process(r"D:\python\pythonw.exe"))
        self.assertFalse(workbench.is_browser_process(""))
        self.assertFalse(workbench.is_browser_process(None))


if __name__ == "__main__":
    unittest.main()
