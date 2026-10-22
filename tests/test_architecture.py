"""架构门禁：模块体量不回长，插件与索引文档不脱节。"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import arch_report  # noqa: E402
from learnsys.modules import load_registry  # noqa: E402

DOC = ROOT / "docs" / "架构-前后端.md"


class ArchitectureTest(unittest.TestCase):
    def test_no_file_over_limit(self):
        bad = arch_report.violations()
        detail = "；".join(f"{row['path']}={row['lines']}行" for row in bad)
        self.assertEqual(bad, [], f"这些文件超过体量红线（改到就先拆）：{detail}")

    def test_doc_lists_all_plugins(self):
        self.assertTrue(DOC.exists(), "缺少 docs/架构-前后端.md")
        doc = DOC.read_text(encoding="utf-8")
        ids = [str(item.get("id") or "") for item in load_registry()["modules"]]
        missing = [item for item in ids if item and item not in doc]
        self.assertEqual(missing, [], f"架构文档没登记这些插件：{missing}")

    def test_doc_has_change_index(self):
        doc = DOC.read_text(encoding="utf-8")
        for section in ("改动定位表", "数据表索引", "插件一览", "体量红线"):
            self.assertIn(section, doc, f"架构文档缺少「{section}」")


if __name__ == "__main__":
    unittest.main(verbosity=2)
