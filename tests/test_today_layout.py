"""今日页结构门禁：防止导航/统计/旧面板又长回首页。

对应 docs/架构-前后端.md 的「今日页准入」：
只放今天会变的内容；工具导航留在侧栏；同一事实一个落点。

P27.2 口径：Web 与 Qt 的三域入口必须一一对应（学习/工作/生活），
深链统一由 `/api/home` 的 `learning.href / work.href / life.href` 下发；
Qt 若窗口过窄，允许只保留入口、不显示明细，但入口集合和 href 仍来自同一份数据。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from learnsys.ask.qt.today_domains import domain_rows

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/pages/today.html").read_text(encoding="utf-8")
JS = (ROOT / "web/js/pages/today.js").read_text(encoding="utf-8")
DOMAINS_JS = (ROOT / "web/js/pages/today-domains.js").read_text(encoding="utf-8")
HOME_CSS = (ROOT / "web/css/home.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
SW = (ROOT / "web/sw.js").read_text(encoding="utf-8")
QT_TODAY = (ROOT / "learnsys/ask/qt/today.py").read_text(encoding="utf-8")
QT_DOMAINS = (ROOT / "learnsys/ask/qt/today_domains.py").read_text(
    encoding="utf-8")


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

    # ---- P27.2 三域首页 ----

    def test_domain_grid_sits_between_hero_and_briefing(self):
        hero = HTML.index('id="stage-hero"')
        grid = HTML.index('id="domain-grid"')
        brief = HTML.index('id="today-briefing"')
        self.assertLess(hero, grid, "三域卡应在 Hero 之后")
        self.assertLess(grid, brief, "三域卡应在简报横条之前")
        self.assertIn('aria-label="学习 / 工作 / 生活"', HTML)

    def test_web_domains_use_home_api_and_server_links(self):
        self.assertIn('api.get("/api/home")', JS)
        self.assertIn("renderDomains(home)", JS)
        for key in ('"learn"', '"work"', '"life"'):
            self.assertIn(key, DOMAINS_JS, f"三域卡缺少 {key}")
        for field in ("learning.href", "work.href", "life.href"):
            self.assertIn(field, DOMAINS_JS,
                          f"深链必须来自 /api/home（{field}），不要在页面里另写一套")

    def test_domain_cards_are_compact_and_stack_on_mobile(self):
        self.assertIn("grid-template-columns: repeat(3", HOME_CSS)
        self.assertIn("@media (max-width: 820px)", HOME_CSS)
        self.assertIn("grid-template-columns: 1fr", HOME_CSS)
        self.assertNotIn("height:", HOME_CSS,
                         "三域卡不设固定高度，避免把今日页撑过 1900px 红线")
        # 每张卡固定三行：标签 / 状态 / 提醒
        for name in ("domain-label", "domain-title", "domain-sub"):
            self.assertIn(name, DOMAINS_JS)
            self.assertIn(f".{name}", HOME_CSS)

    def test_new_assets_are_loaded_and_precached(self):
        self.assertIn('/web/css/home.css', INDEX)
        self.assertIn('"/web/css/home.css"', SW)
        self.assertIn('"/web/js/pages/today-domains.js"', SW)

    def test_qt_and_web_domain_entries_are_one_to_one(self):
        self.assertIn("DomainGrid", QT_TODAY)
        self.assertIn('"/api/home"', QT_TODAY)
        rows = domain_rows(None)
        self.assertEqual([row["key"] for row in rows],
                         ["learn", "work", "life"])
        self.assertEqual([row["href"] for row in rows],
                         ["#/cet6", "#/agents", "#/life"])
        for key in ('"learn"', '"work"', '"life"'):
            self.assertIn(key, QT_DOMAINS)
        self.assertIn('"href"', QT_DOMAINS)

    def test_domain_texts_match_the_p27_contract(self):
        self.assertIn("今日 ${", DOMAINS_JS)
        self.assertIn("到期复习", DOMAINS_JS)
        self.assertIn("进行中", DOMAINS_JS)
        self.assertIn("待排队", DOMAINS_JS)
        self.assertIn("待办", DOMAINS_JS)
        self.assertIn("卡片", DOMAINS_JS)
        self.assertIn("暂无", DOMAINS_JS)
        self.assertIn("暂无", QT_DOMAINS)
        self.assertNotIn('" ".join(', DOMAINS_JS,
                         "JS 字符串没有 split/join 的 Python 写法")


if __name__ == "__main__":
    unittest.main()
