# -*- coding: utf-8 -*-
"""沙箱的 Python 解释器选择：打包版不能把工作台自身当解释器。"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

from learnsys.agent import sandbox


def _which(mapping: dict[str, str]):
    return lambda name: mapping.get(name)


class PythonInterpreterTest(unittest.TestCase):
    def test_source_run_uses_sys_executable(self):
        argv = sandbox._python_argv()
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("-X", argv)

    def test_frozen_prefers_system_python(self):
        with mock.patch.object(sandbox.sys, "frozen", True, create=True), \
                mock.patch.object(sandbox.shutil, "which",
                                  side_effect=_which({"python": r"D:\python\python.exe"})):
            argv = sandbox._python_argv()
            self.assertEqual(argv[0], r"D:\python\python.exe")
            self.assertNotEqual(argv[0], sys.executable)

    def test_frozen_skips_store_alias(self):
        store = r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python.exe"
        with mock.patch.object(sandbox.sys, "frozen", True, create=True), \
                mock.patch.object(sandbox.shutil, "which",
                                  side_effect=_which({"python": store,
                                                      "python3": store,
                                                      "py": r"C:\Windows\py.exe"})):
            argv = sandbox._python_argv()
            self.assertEqual(argv[0], r"C:\Windows\py.exe")
            self.assertIn("-3", argv)

    def test_frozen_without_interpreter(self):
        with mock.patch.object(sandbox.sys, "frozen", True, create=True), \
                mock.patch.object(sandbox.shutil, "which", side_effect=_which({})):
            self.assertEqual(sandbox._python_argv(), [])
            self.assertFalse(sandbox.runtime_available("python"))

    def test_frozen_run_reports_missing_python(self):
        with mock.patch.object(sandbox.sys, "frozen", True, create=True), \
                mock.patch.object(sandbox.shutil, "which", side_effect=_which({})):
            result = sandbox.run("python", "print(1)")
            self.assertFalse(result.ok)
            self.assertIn("没有找到 Python", result.note)


if __name__ == "__main__":
    unittest.main()
