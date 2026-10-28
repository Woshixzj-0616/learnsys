"""内置信息源与每日配额。

源清单只在这里维护；失效时先跑 `tools/briefing_sources_report.py`。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    category: str = "other"
    weight: float = 0.8


@dataclass
class RawItem:
    source_id: str
    source_name: str
    source_weight: float
    category_hint: str
    title: str
    url: str
    summary: str
    published_at: str
    meta: dict = field(default_factory=dict)


# 2026-10-28 实测可用；失效的源不要往这里加（人民网/新华网 RSS 已停更）。
SOURCES: tuple[Source, ...] = (
    Source("chinanews-china", "中国新闻网·时政",
           "https://www.chinanews.com.cn/rss/china.xml", "politics", 1.0),
    Source("chinanews-world", "中国新闻网·国际",
           "https://www.chinanews.com.cn/rss/world.xml", "world", 1.0),
    Source("chinanews-finance", "中国新闻网·财经",
           "https://www.chinanews.com.cn/rss/finance.xml", "other", 0.9),
    Source("chinanews-health", "中国新闻网·健康",
           "https://www.chinanews.com.cn/rss/health.xml", "health", 0.9),
    Source("jiemian", "界面新闻",
           "https://a.jiemian.com/index.php?m=article&a=rss", "other", 0.9),
    Source("qbitai", "量子位",
           "https://www.qbitai.com/feed/", "ai", 0.9),
    Source("ithome", "IT之家",
           "https://www.ithome.com/rss/", "hardware", 0.9),
    Source("ifanr", "爱范儿",
           "https://www.ifanr.com/feed", "hardware", 0.8),
    Source("geekpark", "极客公园",
           "https://www.geekpark.net/rss", "internet", 0.8),
    Source("oschina", "开源中国",
           "https://www.oschina.net/news/rss", "internet", 0.8),
    Source("sspai", "少数派",
           "https://sspai.com/feed", "internet", 0.8),
    Source("hnrss", "Hacker News",
           "https://hnrss.org/frontpage", "internet", 0.7),
    Source("sciencedaily", "ScienceDaily",
           "https://www.sciencedaily.com/rss/top/science.xml", "science", 0.7),
    Source("mit-tr", "MIT Technology Review",
           "https://www.technologyreview.com/feed/", "science", 0.9),
)

# 每天目标 12~15 条；先按类取，再回填。
QUOTAS: dict[str, int] = {
    "politics": 3, "world": 2, "ai": 3, "hardware": 2, "internet": 2,
    "health": 1, "science": 1, "energy": 1,
}
MIN_ITEMS = 12
MAX_ITEMS = 15
MAX_PER_SOURCE = 3
WINDOW_HOURS = 36
CROSS_DAY_DAYS = 3

CATEGORY_LABELS = {
    "politics": "时政", "world": "国际", "ai": "AI", "hardware": "芯片/网络",
    "internet": "互联网/开源", "health": "健康/生医", "science": "前沿科学",
    "energy": "能源/航天", "other": "其他",
}
