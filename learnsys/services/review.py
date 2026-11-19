"""复习调度编排：读旧状态 → FSRS 计算 → 写 `review_state` 与 `review_log`。

业务规则只有一处：这里。路由只做参数与错误转换。
"""
from __future__ import annotations

import datetime as dt
import re

from learnsys import store
from learnsys.services import fsrs
from learnsys.train import content as train_content

ITEM_TYPES = store.REVIEW_ITEM_TYPES

# 英语复习的两个 tab：句子卡来自写作/翻译批改，词卡来自生词本。
# 来源白名单是业务口径，只在这里定义；store 只负责按传进来的条件查。
KINDS = {
    "sentence": {"item_types": ("wrong", "accum"),
                 "sources": ("writing", "translation", "sentence"),
                 "accum_kinds": ("writing",), "quota_types": ("wrong",)},
    "word": {"item_types": ("vocab", "accum"), "sources": (),
             "accum_kinds": ("translation",), "quota_types": ("vocab",)},
}
NEW_PER_DAY = 10   # 每个 tab 每天最多进 10 张新卡


NEW_SHARE = 0.2        # 每轮最多 20% 给新卡（10 张一轮 = 2 张）
OLD_ACCUM_SHARE = 0.5  # 旧每日积累最多占复习位的一半，别再把错题/生词挤掉
QUEUE_POOL = 500       # 先取多少到期候选再排序/混排


def _kind_spec(kind: str) -> dict:
    return KINDS.get(str(kind or "").strip(), {})


def _day_of(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _forget_risk(item: dict, day: dt.date) -> float:
    """0~1：按 FSRS 稳定度估算「今天已经想不起来」的概率；越大越先复习。

    从没复习过的新卡没有稳定度，按最高风险处理（但仍受每轮新卡配额限制）。
    """
    if str(item.get("state") or "") == "new":
        return 1.0
    stability = float(item.get("stability") or 0)
    last = _day_of(item.get("last_review"))
    if stability <= 0 or last is None:
        return 1.0
    elapsed = max(0, (day - last).days)
    return 1.0 - fsrs.retrievability(elapsed, stability)


def _risk_key(item: dict, day: dt.date) -> tuple:
    return (-_forget_risk(item, day), str(item.get("due") or ""),
            str(item.get("item_type") or ""), int(item.get("item_id") or 0))


def _is_today_accum(item: dict, day: str) -> bool:
    return (item.get("item_type") == "accum"
            and str(item.get("accum_day") or "")[:10] == day)


def _interleave(primary: list[dict], extras: list[dict]) -> list[dict]:
    """把新卡均匀插进复习卡，不再永远堆在末尾。"""
    if not extras:
        return list(primary)
    if not primary:
        return list(extras)
    total = len(primary) + len(extras)
    positions = [((index + 1) * total) // (len(extras) + 1)
                 for index in range(len(extras))]
    out: list[dict] = []
    extra_index = primary_index = 0
    for slot in range(total):
        if extra_index < len(extras) and slot == positions[extra_index]:
            out.append(extras[extra_index])
            extra_index += 1
        elif primary_index < len(primary):
            out.append(primary[primary_index])
            primary_index += 1
        else:
            out.append(extras[extra_index])
            extra_index += 1
    return out


def _drop_word_duplicates(conn, items: list[dict]) -> list[dict]:
    """词 tab 去重：生词卡优先，同一 alias 的 accum 卡让位。

    `seed_review_states` 已经会清理历史重叠；这里保证即使状态还在，
    同一英文也不会以「生词卡 + 每日积累卡」出现两次。
    """
    vocab_aliases = store.active_vocab_aliases(conn)
    seen: list[set[str]] = []
    kept: list[dict] = []
    for item in items:
        if item.get("item_type") != "vocab":
            continue
        aliases = store.word_aliases(item.get("word"))
        if any(aliases & other for other in seen):
            continue
        seen.append(aliases)
        kept.append(item)
    for item in items:
        if item.get("item_type") == "vocab":
            continue
        if (item.get("item_type") == "accum"
                and item.get("accum_kind") == "translation"):
            aliases = store.word_aliases(item.get("meaning"))
            if aliases & vocab_aliases:
                continue
            if any(aliases & other for other in seen):
                continue
            seen.append(aliases)
        kept.append(item)
    return kept


def _compose_queue(items: list[dict], *, day: str, limit: int,
                   new_left: int | None, has_kind: bool) -> list[dict]:
    """一轮复习的取卡规则（唯一落点）。

    1. 当天生成的每日积累排最前（写作 2 / 翻译 8）；
    2. 其余卡按 FSRS 遗忘风险从高到低混排，旧积累最多占复习位一半；
    3. 新词/新错题按每轮 20% 插入，且不超过当天剩余新卡配额。
    """
    size = max(1, int(limit or 10))
    day_text = str(day or "")[:10]
    day_date = _day_of(day_text) or dt.date.today()
    if not has_kind:
        # 错题本 / MCP 的通用队列没有两个 tab 的配额规则，保持到期日顺序。
        ordered = sorted(items, key=lambda item: (
            str(item.get("due") or ""), str(item.get("item_type") or ""),
            int(item.get("item_id") or 0)))
        return ordered[:size]

    today_accum = [item for item in items if _is_today_accum(item, day_text)]
    rest = [item for item in items if not _is_today_accum(item, day_text)]
    today_accum.sort(key=lambda item: (str(item.get("due") or ""),
                                       int(item.get("item_id") or 0)))
    selection = today_accum[:size]
    remaining = size - len(selection)
    if remaining <= 0:
        return selection

    review_pool: list[dict] = []
    new_pool: list[dict] = []
    for item in rest:
        if item.get("item_type") == "accum":
            review_pool.append(item)      # 旧积累降级为普通复习卡
        elif str(item.get("state") or "") == "new":
            new_pool.append(item)
        else:
            review_pool.append(item)
    review_pool.sort(key=lambda item: _risk_key(item, day_date))
    new_pool.sort(key=lambda item: (str(item.get("due") or ""),
                                    str(item.get("item_type") or ""),
                                    int(item.get("item_id") or 0)))

    new_slots = min(max(1, round(size * NEW_SHARE)), remaining,
                    max(0, int(new_left or 0)), len(new_pool))
    review_slots = remaining - new_slots
    picked: list[dict] = []
    seen: set[tuple[str, int]] = set()
    accum_used = 0
    accum_cap = max(1, round(review_slots * OLD_ACCUM_SHARE)) if review_slots else 0
    for item in review_pool:
        if len(picked) >= review_slots:
            break
        key = (str(item.get("item_type") or ""), int(item.get("item_id") or 0))
        if key in seen:
            continue
        if item.get("item_type") == "accum":
            if accum_used >= accum_cap:
                continue
            accum_used += 1
        picked.append(item)
        seen.add(key)
    if len(picked) < review_slots:
        # 没有别的卡可补时，再用剩下的旧积累填满这一轮。
        for item in review_pool:
            if len(picked) >= review_slots:
                break
            key = (str(item.get("item_type") or ""), int(item.get("item_id") or 0))
            if key in seen:
                continue
            picked.append(item)
            seen.add(key)
    result = selection + _interleave(picked, new_pool[:new_slots])
    for item in result:
        if str(item.get("state") or "") != "new":
            item["forget_risk"] = round(_forget_risk(item, day_date), 3)
    return result


def _introduced_today(conn, item_types: tuple, day: str,
                      sources: tuple = ()) -> int:
    """今天已经正式复习过的新卡数（review_log 里 state_before='new'）。

    `sources` 与到期队列同口径：只算本 tab 白名单来源的错题，避免在错题本
    复习 manual/quiz 卡把英语句子 tab 的新卡配额吃光。
    """
    types = tuple(t for t in item_types if t in ITEM_TYPES)
    return store.count_introduced(conn, day=day, item_types=types,
                                  sources=sources)


def _exists(conn, item_type: str, item_id: int) -> bool:
    if item_type == "wrong":
        return store.get_wrong_item(conn, item_id) is not None
    if item_type == "vocab":
        return store.get_vocab(conn, item_id) is not None
    if item_type == "accum":
        return store.accum_item(conn, item_id) is not None
    return False


def _new_state() -> dict:
    return {
        "state": "new", "due": dt.date.today().isoformat(), "stability": 0.0,
        "difficulty": 0.0, "reps": 0, "lapses": 0, "last_review": "",
        "scheduled_days": 0, "elapsed_days": 0,
    }


def review(conn, item_type: str, item_id: int, rating: int,
           now: dt.datetime | None = None) -> dict:
    """提交一次复习；返回新状态与下次到期日。"""
    if item_type not in ITEM_TYPES:
        raise ValueError("不支持的卡片类型：" + str(item_type))
    if rating not in (1, 2, 3, 4):
        raise ValueError("评分必须是 1–4")
    if not _exists(conn, item_type, int(item_id)):
        raise LookupError("卡片不存在")
    store.seed_review_states(conn)
    old = store.get_review_state(conn, item_type, int(item_id)) or _new_state()
    # 同一张卡、同一步的间隔抖动结果固定；不同卡错开到相邻几天。
    seed = f"{item_type}:{int(item_id)}:{int(old.get('reps') or 0)}"
    new = fsrs.schedule(old, int(rating), now, seed=seed)
    store.save_review_state(conn, item_type, int(item_id), **new)
    store.add_review_log(
        conn, item_type=item_type, item_id=int(item_id), rating=int(rating),
        state_before=old.get("state") or "new", due_before=old.get("due") or "",
        due_after=new["due"], stability=new["stability"],
        difficulty=new["difficulty"], elapsed_days=new["elapsed_days"],
        scheduled_days=new["scheduled_days"])
    return {
        "state": new,
        "next_review": new["due"],
        "rating": int(rating),
        "rating_name": fsrs.RATING_NAMES[int(rating)],
        "scheduled_days": new["scheduled_days"],
    }


def review_wrong_item(conn, item_id: int, result: str) -> dict | None:
    """兼容旧调用：remember → FSRS 评分 3，forgot → 评分 1。"""
    rating = 1 if str(result or "").strip().lower() == "forgot" else 3
    try:
        review(conn, "wrong", int(item_id), rating)
    except LookupError:
        return None
    return store.get_wrong_item(conn, int(item_id))


def bump_review_stage(conn, item_ids: list[int]) -> None:
    """兼容旧名字：按「记得」推进一次 FSRS。"""
    for item_id in item_ids or []:
        review_wrong_item(conn, int(item_id), "remember")


_TOPIC_SUFFIX = re.compile(r"（[^）]*）$")


def _writing_topics() -> list[tuple[str, str]]:
    """第 3 关换主题池：复用写作题库标题，去掉「（2025-12 第三套）」这类来源后缀。"""
    rows: list[tuple[str, str]] = []
    for row in train_content.writing_items():
        title = _TOPIC_SUFFIX.sub("", str(row.get("title") or "").strip()).strip()
        if title:
            rows.append((str(row.get("id") or ""), title))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def _cjk_bigrams(text: str) -> set[str]:
    chars = [ch for ch in str(text or "") if 0x4E00 <= ord(ch) <= 0x9FFF]
    return {chars[index] + chars[index + 1] for index in range(len(chars) - 1)}


def _topic_is_distinct(title: str, example_zh: str) -> bool:
    """主题和原例句太像就会泄题，至少隔开两个中文二字片段。"""
    if not example_zh:
        return True
    return len(_cjk_bigrams(title) & _cjk_bigrams(example_zh)) < 2


def _attach_topics(items: list[dict]) -> None:
    """只给写作句型卡附换主题；主题随 reps 轮换，同一天重复读队列不变。"""
    topics = _writing_topics()
    if not topics:
        return
    for item in items:
        if item.get("item_type") != "accum":
            continue
        if item.get("accum_kind") != "writing":
            continue
        example_zh = str(item.get("example_zh") or "").strip()
        pool = [title for _, title in topics
                if _topic_is_distinct(title, example_zh)]
        if not pool:
            continue
        seed = int(item.get("item_id") or 0) + int(item.get("reps") or 0)
        item["topic"] = pool[seed % len(pool)]


def queue(conn, *, limit: int = 50, item_type: str = "",
          kind: str = "", today=None) -> dict:
    store.seed_review_states(conn)
    day = str(today or dt.date.today().isoformat())[:10]
    spec = _kind_spec(kind)
    if spec:
        # 每日积累是当天的固定 10 张，不占旧错题/生词的 10 张新卡配额。
        introduced = _introduced_today(
            conn, spec.get("quota_types", spec["item_types"]), day,
            sources=spec.get("sources", ()))
        new_left = max(0, NEW_PER_DAY - introduced)
        items = store.due_review_items(
            conn, limit=QUEUE_POOL, today=day,
            item_types=spec["item_types"], sources=spec["sources"],
            accum_kinds=spec.get("accum_kinds", ()))
        if kind == "word":
            items = _drop_word_duplicates(conn, items)
        picked = _compose_queue(items, day=day, limit=limit,
                                new_left=new_left, has_kind=True)
        _attach_topics(picked)
        return {"items": picked, "count": len(picked), "kind": kind,
                "new_per_day": NEW_PER_DAY, "new_remaining": new_left,
                "quota_types": list(spec.get("quota_types", spec["item_types"]))}
    items = store.due_review_items(conn, limit=limit, item_type=item_type,
                                   today=day)
    picked = _compose_queue(items, day=day, limit=limit, new_left=None,
                            has_kind=False)
    _attach_topics(picked)
    return {"items": picked, "count": len(picked)}


def due_counts(conn, today=None) -> dict:
    """今日页用：只数句子/词各有多少到期，不建队列、不写复习状态。"""
    day = str(today or dt.date.today().isoformat())[:10]
    return {kind: store.due_review_count(
        conn, today=day, item_types=spec["item_types"],
        sources=spec["sources"], accum_kinds=spec.get("accum_kinds", ()))
        for kind, spec in KINDS.items()}


def stats(conn, item_type: str = "", kind: str = "", today=None) -> dict:
    store.seed_review_states(conn)
    spec = _kind_spec(kind)
    if spec:
        return store.review_counts(
            conn, today=today, item_types=spec["item_types"],
            sources=spec["sources"], accum_kinds=spec.get("accum_kinds", ()))
    return store.review_stats(conn, item_type=item_type, today=today)


def recent_log(conn, limit: int = 20) -> dict:
    return {"items": store.recent_review_log(conn, limit=limit)}
