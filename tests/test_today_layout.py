"""今日页结构门禁：防止导航/统计/旧面板又长回首页。

对应 docs/架构-前后端.md 的「今日页准入」：
只放今天会变的内容；工具导航留在侧栏；同一事实一个落点。
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/pages/today.html").read_text(encoding="utf-8")
JS = (ROOT / "web/js/pages/today.js").read_text(encoding="utf-8")


class TodayLayoutTest(unittest.TestCase):
    def test_removed_blocks_stay_removed(self):
        for token in ("plugin-grid", "today-actions", "today-stats",
                      "cet6-panel", "today-lower", "所有工具"):
            self.assertNotIn(token, HTML, f"今日页不应再出现 {token}")

    def test_core_blocks_are_registered(self):
        for block in ("stage-hero", "today-briefing", "continue-card",
                      "today-timeline", "week-bars", "today-facts", "ach-card"):
            self.assertIn(f'id="{block}"', HTML, f"缺少今日页区块 {block}")

    def test_briefing_is_a_full_width_band_before_columns(self):
        brief = HTML.index('id="today-briefing"')
        cols = HTML.index('class="cols"')
        self.assertLess(brief, cols, "简报横条必须在双栏之前")
        self.assertIn("brief-band", HTML)

    def test_timeline_is_a_grouped_rail_with_summary(self):
        self.assertIn('class="tl-group"', JS)
        self.assertIn('class="tl-rail"', JS)
        self.assertIn("plain(ask.answer", JS, "时间线只放摘要，不放正文")
        self.assertIn("asks.slice(0, 6)", JS, "时间线最多展示 6 条")

    def test_actions_merge_into_continue_card(self):
        self.assertIn("renderAlts", JS)
        self.assertIn('id="continue-alts"', HTML)


if __name__ == "__main__":
    unittest.main()
