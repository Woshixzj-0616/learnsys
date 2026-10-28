"""候选清洗：URL/标题去重、关键词分类、按类配额挑选。"""
from __future__ import annotations

import dataclasses
import datetime as dt
import difflib
import hashlib
import re
import urllib.parse

from .sources import (
    CATEGORY_LABELS,
    MAX_ITEMS,
    MAX_PER_SOURCE,
    MIN_ITEMS,
    QUOTAS,
    WINDOW_HOURS,
    RawItem,
)

_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "from_source", "share_token", "share_source", "ref",
    "referrer", "fbclid", "gclid",
}

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "politics": ("国务院", "中央", "政策", "会议", "政府", "主席", "总理",
                 "人大", "政协", "部署", "改革", "监管", "中共中央", "常务会议"),
    "world": ("美国", "俄罗斯", "乌克兰", "欧洲", "欧盟", "日本", "韩国",
              "联合国", "外交", "中东局势", "中东地区", "以色列", "加沙",
              "白宫", "北约", "特朗普", "伊朗", "朝鲜", "俄乌"),
    "ai": ("人工智能", "大模型", "智能体", "机器学习", "深度学习", "生成式",
           "openai", "deepseek", "anthropic", "gemini", "claude", "gpt",
           "llm", "agi", "ai"),
    "hardware": ("芯片", "半导体", "光刻", "gpu", "cpu", "服务器", "5g", "6g",
                 "交换机", "路由器", "数据中心", "算力", "英伟达", "台积电",
                 "华为", "晶圆", "封装", "存储", "网络设备", "机器人",
                 "自动驾驶"),
    "internet": ("开源", "编程", "开发者", "软件", "互联网", "平台", "github",
                 "linux", "数据库", "前端", "后端", "代码", "应用", "浏览器",
                 "云原生", "docker", "kubernetes"),
    "health": ("医疗", "医药", "新药", "临床", "生物", "基因", "疫苗", "医院",
               "疾病", "癌症", "免疫", "细胞", "诊断"),
    "science": ("科研", "论文", "物理", "化学", "材料", "天文", "量子", "实验",
                "科学家", "研究", "nature", "science"),
    "energy": ("新能源", "固态电池", "动力电池", "光伏", "储能", "核能", "核电",
               "氢能", "风电", "电网", "石油", "天然气", "化工", "航天",
               "火箭", "卫星", "空间站", "探月", "发射", "新能源汽车"),
}

_POSITIVE = ("发布", "突破", "首次", "获批", "开源", "融资", "政策", "研发",
             "上线", "合作", "收购", "量产", "标准", "试验", "临床", "launch",
             "release", "open source", "funding", "breakthrough")
_NEGATIVE = ("开箱", "图赏", "促销", "优惠", "降价", "上手", "配色", "壁纸",
             "铃声", "预约", "到手价", "优惠券")
# 纯促销/带货稿直接不进入候选，别占“科技前沿”的名额。
_DROP = ("碎屏保", "只换不修", "晒单", "京豆", "到手价", "首发赠",
         "限时特惠", "国补价", "优惠券", "券后",
         "早报｜", "极客早知道", "派早报", "社区速递", "游戏首日补丁",
         "归母净利润", "净利润同比", "营收同比", "财报",
         "产业社区", "经开区", "产业园", "高新区", "集中修",
         "片单", "大剧", "剧集", "票房", "综艺", "电视剧")


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(str(url or "").strip())
    query = [(key, value) for key, value in urllib.parse.parse_qsl(
        parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING and not key.lower().startswith("utm_")]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((
        parts.scheme.lower(), parts.netloc.lower(), path,
        urllib.parse.urlencode(sorted(query)), "",
    ))


def url_key(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    text = str(title or "").lower()
    return re.sub(r"[^\w一-鿿]+", "", text)


def title_similarity(left: str, right: str) -> float:
    left, right = normalize_title(left), normalize_title(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.92
    shortest = min(len(left), len(right))
    if shortest < 6 or abs(len(left) - len(right)) > max(8, shortest // 2):
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def classify(item: RawItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    title = str(item.title or "").lower()
    best, best_hits = "", 0
    for category, words in _KEYWORDS.items():
        hits = 0
        for word in words:
            if word == "ai":
                # 单独一个 AI 太泛：只在标题里出现才算，避免正文提一句就归类。
                hits += 1 if re.search(r"\bai\b", title) else 0
            elif word in text:
                hits += 1
        if hits > best_hits:
            best, best_hits = category, hits
    if best:
        return best
    if item.category_hint in CATEGORY_LABELS and item.category_hint != "other":
        return item.category_hint
    return "other"


def _moment(value: str, fallback: dt.datetime) -> dt.datetime:
    try:
        return dt.datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return fallback


def _score(item: RawItem, now: dt.datetime) -> float:
    moment = _moment(item.published_at, now)
    age = max(0.0, (now - moment).total_seconds() / 3600.0)
    score = max(0.0, 3.0 * (1.0 - age / WINDOW_HOURS))
    score += max(0.0, min(float(item.source_weight or 0.8), 1.0)) * 2.0
    text = f"{item.title} {item.summary}".lower()
    score += min(2.4, 0.8 * sum(1 for word in _POSITIVE if word in text))
    score -= min(3.0, 1.0 * sum(1 for word in _NEGATIVE if word in text))
    if item.meta.get("time_estimated"):
        score -= 1.5
    return score


def select(items: list[RawItem], *, now: dt.datetime | None = None,
           seen_url_keys=(), seen_titles=(), quotas=None,
           max_items: int = MAX_ITEMS, min_items: int = MIN_ITEMS,
           max_per_source: int = MAX_PER_SOURCE) -> list[dict]:
    """近 36h → 去重 → 分类 → 每类配额 → 回填。返回按分数排序的 dict。"""
    now = now or dt.datetime.now()
    quotas = dict(quotas or QUOTAS)
    seen_urls = set(seen_url_keys or ())
    old_titles = list(seen_titles or ())
    # 先过时间窗 / 已发过的 URL，再算分（分数依赖时间）。
    candidates: list[dict] = []
    for item in items:
        key = url_key(item.url)
        if key in seen_urls:
            continue
        moment = _moment(item.published_at, now)
        if (now - moment).total_seconds() > WINDOW_HOURS * 3600:
            continue
        text = f"{item.title} {item.summary}"
        if any(word in text for word in _DROP):
            continue
        row = dataclasses.asdict(item)
        row["url_key"] = key
        row["category"] = classify(item)
        row["category_label"] = CATEGORY_LABELS.get(row["category"], "其他")
        row["score"] = _score(item, now)
        candidates.append(row)
    candidates.sort(key=lambda row: (row["score"], row["published_at"]), reverse=True)

    # 同批按类去重；跨天标题去重对最近 3 天都生效。
    kept_by_category: dict[str, list[str]] = {}
    deduped: list[dict] = []
    for row in candidates:
        if any(title_similarity(row["title"], old) >= 0.85 for old in old_titles):
            continue
        same = kept_by_category.setdefault(row["category"], [])
        if any(title_similarity(row["title"], other) >= 0.85 for other in same):
            continue
        same.append(row["title"])
        deduped.append(row)

    selected: list[dict] = []
    used: set[int] = set()
    source_count: dict[str, int] = {}
    # 稀缺类别先挑，避免高频源被前面的类别占满配额。
    available: dict[str, int] = {}
    for row in deduped:
        available[row["category"]] = available.get(row["category"], 0) + 1
    order = sorted(quotas, key=lambda name: (available.get(name, 0), list(quotas).index(name)))
    for category in order:
        quota = quotas[category]
        picked = 0
        for index, row in enumerate(deduped):
            if index in used or row["category"] != category:
                continue
            if source_count.get(row["source_id"], 0) >= max_per_source:
                continue
            selected.append(row)
            used.add(index)
            source_count[row["source_id"]] = source_count.get(row["source_id"], 0) + 1
            picked += 1
            if picked >= quota or len(selected) >= max_items:
                break
        if len(selected) >= max_items:
            break

    # 配额不足时按全局分数回填，仍受“同源最多 N 条”约束。
    if len(selected) < min_items:
        for index, row in enumerate(deduped):
            if len(selected) >= max_items:
                break
            if index in used:
                continue
            if source_count.get(row["source_id"], 0) >= max_per_source:
                continue
            selected.append(row)
            used.add(index)
            source_count[row["source_id"]] = source_count.get(row["source_id"], 0) + 1

    selected.sort(key=lambda row: row["score"], reverse=True)
    return selected
