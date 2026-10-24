# -*- coding: utf-8 -*-
"""深色视觉（R3.10）：令牌装载、QSS 渲染、调色板与真实像素。"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from learnsys.ask.qt import style, tokens  # noqa: E402
from learnsys.ask.qt.settings import SettingsWindow  # noqa: E402
from learnsys.ask.qt.widgets import FieldRow, Section  # noqa: E402
from tests.test_qt_settings import FakeApiClient  # noqa: E402


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestTokenParsing(unittest.TestCase):
    def test_解析正常与注释(self):
        text = """
        /* 头顶注释 --bg: #fff; 不算 */
        :root {
          --bg: #1b1e23;
          --text: #dfe6ee;   /* 行内注释 */
          --accent: #4d8bff;
        }
        """
        result = tokens.load_tokens(text)
        self.assertEqual(result["--bg"], "#1b1e23")
        self.assertEqual(result["--text"], "#dfe6ee")
        self.assertEqual(result["--accent"], "#4d8bff")

    def test_值含逗号和括号(self):
        text = ":root { --accent-soft: rgba(77, 139, 255, 0.13); }"
        self.assertEqual(tokens.load_tokens(text)["--accent-soft"],
                         "rgba(77, 139, 255, 0.13)")

    def test_字体列表原样保留(self):
        text = ':root { --font-ui: "Microsoft YaHei UI", system-ui, sans-serif; }'
        self.assertEqual(tokens.load_tokens(text)["--font-ui"],
                         '"Microsoft YaHei UI", system-ui, sans-serif')

    def test_只看_root_块(self):
        text = """
        .sidebar { --bg: #ffffff; }
        :root { --bg: #1b1e23; }
        .other { --text: #000000; }
        """
        result = tokens.load_tokens(text)
        self.assertEqual(result, {"--bg": "#1b1e23"})

    def test_空文件和缺文件都回退(self):
        empty = tokens.load_tokens("")
        self.assertEqual(empty, {})
        with tempfile.TemporaryDirectory() as folder:
            missing = pathlib.Path(folder) / "nope.css"
            self.assertEqual(tokens.read_web_tokens(missing),
                             tokens.default_tokens())
            empty_file = pathlib.Path(folder) / "empty.css"
            empty_file.write_text("", encoding="utf-8")
            self.assertEqual(tokens.read_web_tokens(empty_file),
                             tokens.default_tokens())

    def test_仓库_tokens_css_齐备(self):
        values = tokens.read_web_tokens()
        for key in tokens.REQUIRED:
            self.assertIn(key, values)
            self.assertTrue(str(values[key]).strip(), key)

    def test_像素值换算(self):
        self.assertEqual(tokens.px({"--s5": "24px"}, "--s5"), 24)
        self.assertEqual(tokens.px({"--s5": "bad"}, "--s5", 12), 12)
        self.assertEqual(tokens.px({}, "--s5", 7), 7)

    def test_打包后在_MEIPASS_下读同一份(self):
        with tempfile.TemporaryDirectory() as folder:
            css = pathlib.Path(folder) / "web" / "css"
            css.mkdir(parents=True)
            (css / "tokens.css").write_text(
                ":root { --bg: #010203; }", encoding="utf-8")
            with mock.patch.object(sys, "_MEIPASS", folder, create=True):
                self.assertEqual(tokens.read_web_tokens()["--bg"], "#010203")


class TestQss(unittest.TestCase):
    def test_模板填满且没有漏占位(self):
        qss = style.render_qss()
        self.assertIn("#1b1e23", qss)
        self.assertIn("#21252b", qss)
        self.assertNotIn("{{", qss)
        self.assertNotIn("}}", qss)

    def test_缺键用兜底不报错(self):
        qss = style.render_qss({"--bg": "#000000"})
        self.assertIn("#000000", qss)
        self.assertIn(tokens.default_tokens()["--text"], qss)

    def test_不再有浅色底(self):
        qss = style.render_qss().lower()
        for light in ("#f5f6fa", "#ffffff", "#f1f3f8", "#e3e6ee"):
            self.assertNotIn(light, qss, light)

    def test_下拉弹层与滚动条有深色规则(self):
        qss = style.render_qss()
        self.assertIn("QComboBox QAbstractItemView", qss)
        self.assertIn("QScrollBar::handle:vertical", qss)
        self.assertIn("QToolTip", qss)

    def test_图标文件生成(self):
        style._ICON_CACHE.clear()
        icons = style._ICON_CACHE
        path = style._icon("check", style.ON_ACCENT, *style._CHECK)
        self.assertTrue(path)
        self.assertTrue(pathlib.Path(path).is_file())
        self.assertTrue(icons)

    def test_rgba_转_QColor(self):
        value = style.color("rgba(77, 139, 255, 0.13)")
        self.assertTrue(value.isValid())
        self.assertEqual((value.red(), value.green(), value.blue()), (77, 139, 255))
        self.assertAlmostEqual(value.alpha(), 33, delta=1)


class TestSettingsDark(unittest.TestCase):
    def setUp(self):
        _app()
        self.api = FakeApiClient()
        self.window = SettingsWindow(self.api)
        self.addCleanup(self.window.deleteLater)
        self.window.load()
        self.api.ready.emit()

    def test_窗口样式表非空(self):
        self.assertTrue(self.window.styleSheet().strip())

    def test_调色板是深色(self):
        palette = self.window.palette()
        window = palette.color(QtGui.QPalette.ColorRole.Window).name()
        base = palette.color(QtGui.QPalette.ColorRole.Base).name()
        self.assertEqual(window, "#1b1e23")
        self.assertEqual(base, "#181b20")

    def test_版心与窗口尺寸(self):
        self.assertEqual(self.window.maximumWidth(), 16777215)  # 窗口不设上限
        self.assertIsNotNone(self.window.column_widget)
        self.assertEqual(self.window.column_widget.maximumWidth(), 780)
        self.assertEqual((self.window.width(), self.window.height()),
                         style.fit_size(style.WINDOW_SIZE))
        self.assertLessEqual(self.window.width(), 900)
        self.assertLessEqual(self.window.height(), 760)
        self.assertEqual(self.window.minimumWidth(), 640)
        self.assertEqual(self.window.minimumHeight(), 420)

    def test_窗口按工作区收缩(self):
        class FakeScreen:
            @staticmethod
            def availableGeometry():
                return QtCore.QRect(0, 0, 800, 600)

        with mock.patch.object(QtWidgets.QApplication, "primaryScreen",
                               staticmethod(lambda: FakeScreen())):
            self.assertEqual(style.fit_size((900, 760)), (760, 560))
            self.assertEqual(style.fit_size((640, 420)), (640, 420))

    def test_字段左列最小宽度(self):
        row = FieldRow("标签", QtWidgets.QLineEdit())
        self.addCleanup(row.deleteLater)
        self.assertEqual(row.layout().columnMinimumWidth(0), 190)

    def test_分组卡片保留深色底(self):
        section = Section("标题", tokens=self.window.tokens)
        self.addCleanup(section.deleteLater)
        self.assertTrue(section.testAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground))

    def test_渲染像素是深色(self):
        self.window.show()
        _app().processEvents()
        image = self.window.grab().toImage()
        self.assertFalse(image.isNull())
        for x, y in ((2, 2), (image.width() - 3, 2),
                     (2, image.height() - 3), (image.width() // 2, 2)):
            pixel = image.pixelColor(x, y)
            self.assertLess(pixel.lightness(), 80, (x, y, pixel.name()))
        self.assertEqual(image.pixelColor(2, 2).name(), "#1b1e23")


if __name__ == "__main__":
    unittest.main(verbosity=2)
