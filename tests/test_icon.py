# -*- coding: utf-8 -*-
"""图标：尺寸、透明角、ICO 档位。"""
from __future__ import annotations

import os
import pathlib
import struct
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtGui  # noqa: E402

from learnsys import config  # noqa: E402
from learnsys.ask import icon  # noqa: E402


def _app() -> QtGui.QGuiApplication:
    app = QtGui.QGuiApplication.instance()
    return app or QtGui.QGuiApplication([])


class IconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def test_small_icon_has_opaque_core_and_transparent_corner(self):
        pix = icon.pixmap(64)
        self.assertFalse(pix.isNull())
        image = pix.toImage()
        self.assertGreater(image.pixelColor(32, 32).alpha(), 200)     # 中心是实底
        self.assertLess(image.pixelColor(1, 1).alpha(), 60)           # 圆角外基本透明（抗锯齿会留一点）
        # 不是一个纯色方块：书页的白色和蓝底要能分出层次
        colors = {image.pixelColor(x, y).name() for x in (10, 32, 54) for y in (20, 32, 50)}
        self.assertGreater(len(colors), 3)

    def test_maskable_is_full_bleed(self):
        image = icon.pixmap(64, maskable=True).toImage()
        for x, y in ((1, 1), (62, 1), (1, 62), (62, 62)):
            self.assertGreater(image.pixelColor(x, y).alpha(), 200, (x, y))

    def test_ico_has_all_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "icon.ico"
            self.assertIsNotNone(icon.write_ico(path, force=True))
            data = path.read_bytes()
            reserved, kind, count = struct.unpack("<HHH", data[:6])
            self.assertEqual((reserved, kind), (0, 1))
            sizes = [256 if data[6 + i * 16] == 0 else data[6 + i * 16]
                     for i in range(count)]
            self.assertEqual(sizes, list(icon.SIZES))

    def test_web_png_sizes(self):
        expected = {
            "icon-192.png": 192,
            "icon-512.png": 512,
            "icon-maskable-512.png": 512,
            "apple-touch-icon.png": 180,
        }
        base = pathlib.Path(config.ROOT) / "web" / "icons"
        for name, size in expected.items():
            data = (base / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", name)
            width, height = struct.unpack(">II", data[16:24])
            self.assertEqual((width, height), (size, size), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
