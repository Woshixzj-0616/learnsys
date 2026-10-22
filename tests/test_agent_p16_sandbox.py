"""P16.2：代码运行沙箱 + 资料/文件写入。"""
from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from learnsys import store
from learnsys.agent import sandbox, tools


class SandboxTest(unittest.TestCase):
    def test_network_guard_blocks_python_socket(self):
        findings = sandbox.network_findings('import socket\nsocket.socket()')
        self.assertTrue(findings)
        result = sandbox.run("python", "import socket\nsocket.socket()")
        self.assertFalse(result.ok)
        self.assertIn("禁网", result.note)

    def test_network_guard_blocks_cpp_winsock(self):
        code = '#include <winsock2.h>\nint main(){return 0;}'
        self.assertTrue(sandbox.network_findings(code))

    def test_network_guard_blocks_url(self):
        self.assertTrue(sandbox.network_findings(
            'print("https://example.com")'))

    def test_python_success(self):
        result = sandbox.run("python", "print(6 * 7)")
        self.assertTrue(result.ok, result.stderr)
        self.assertIn("42", result.stdout)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.truncated)

    def test_python_syntax_error_is_chinese(self):
        result = sandbox.run("python", "print(")
        self.assertFalse(result.ok)
        self.assertIn("运行失败", result.note)
        self.assertTrue(result.stderr)

    def test_timeout_kills_process(self):
        result = sandbox.run("python", "while True:\n    pass", timeout=1.5)
        self.assertFalse(result.ok)
        self.assertTrue(result.timed_out)
        self.assertIn("超时", result.note)

    def test_output_cap(self):
        result = sandbox.run("python", "print('x' * 20000)", output_limit=1024)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.stdout), 1100)

    @unittest.skipUnless(shutil.which("g++"), "本机没有 g++")
    def test_cpp_success(self):
        result = sandbox.run("cpp", '#include <iostream>\n'
                                    'int main(){std::cout << 6*7 << "\\n";}')
        self.assertTrue(result.ok, result.stderr + result.note)
        self.assertIn("42", result.stdout)

    @unittest.skipUnless(shutil.which("g++"), "本机没有 g++")
    def test_cpp_compile_error_is_chinese(self):
        result = sandbox.run("cpp", "int main() { this is not cpp; }")
        self.assertFalse(result.ok)
        self.assertIn("编译失败", result.note)
        self.assertTrue(result.stderr)


class WriteToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.ctx = tools.ToolContext(data_root=self.root,
                                     db_path=self.root / "learning.db")

    def test_save_material_note_appears_in_materials(self):
        text, preview, ok = tools.execute("save_material_note", {
            "title": "栈的复习笔记",
            "content": "栈是后进先出。\n\n队列是先进先出。",
            "tags": "数据结构,栈",
        }, self.ctx)
        self.assertTrue(ok, text)
        self.assertIn("已保存", text)
        self.assertIn("资料 #", text)
        conn = store.connect(self.root / "learning.db")
        try:
            items = store.list_materials(conn)
            detail = store.get_material(conn, items[0]["id"]) if items else {}
        finally:
            conn.close()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "栈的复习笔记")
        self.assertIn("后进先出", detail["body"])

    def test_save_material_note_dedupes_same_body(self):
        args = {"title": "笔记", "content": "同一段内容"}
        first, _, _ = tools.execute("save_material_note", args, self.ctx)
        second, _, ok = tools.execute("save_material_note", args, self.ctx)
        self.assertTrue(ok)
        conn = store.connect(self.root / "learning.db")
        try:
            items = store.list_materials(conn)
        finally:
            conn.close()
        self.assertEqual(len(items), 1)
        self.assertIn("已经存在", second)
        self.assertIn("资料 #", first)

    def test_write_study_file_saves_under_study_folder(self):
        text, preview, ok = tools.execute("write_study_file", {
            "relative_path": "代码/栈示例.cpp",
            "content": "int main(){return 0;}",
        }, self.ctx)
        self.assertTrue(ok, text)
        target = self.root / "学习档案" / "代码" / "栈示例.cpp"
        self.assertTrue(target.exists())
        self.assertIn("学习档案", preview)

    def test_write_study_file_rejects_traversal_and_absolute(self):
        for path in ("../escape.md", "/etc/passwd", "..\\escape.md"):
            text, _, ok = tools.execute("write_study_file", {
                "relative_path": path, "content": "x"}, self.ctx)
            self.assertFalse(ok, path)
            self.assertIn("只能", text)

    def test_write_study_file_rejects_binary_extension(self):
        text, _, ok = tools.execute("write_study_file", {
            "relative_path": "程序.exe", "content": "MZ"}, self.ctx)
        self.assertFalse(ok)
        self.assertIn("扩展名", text)

    def test_run_code_tool(self):
        text, preview, ok = tools.execute("run_code", {
            "language": "python", "code": "print('你好')"}, self.ctx)
        self.assertTrue(ok, text)
        self.assertIn("你好", text)
        self.assertIn("运行成功", preview)


if __name__ == "__main__":
    unittest.main()
