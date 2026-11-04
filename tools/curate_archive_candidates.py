"""整理档案抽取候选：只留学习/个人长期画像，项目状态与一次性技术内容归档。

    .venv/Scripts/python.exe tools/curate_archive_candidates.py --dry-run
    .venv/Scripts/python.exe tools/curate_archive_candidates.py --apply

可回滚：只把 status 改成 archived（archived_reason=curate_low_value），不删行。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import store

LEARN = ("学习", "复习", "听力", "六级", "英语", "算法", "数据结构", "笔记",
         "代码", "讲解", "练习", "考试", "记忆", "总结", "错题", "图书馆",
         "背诵", "刷题", "课程", "写作", "翻译", "阅读", "口语", "编程",
         "计算机", "网络", "C++", "Python", "知识点", "解题")
LIFE = ("作息", "习惯", "运动", "睡眠", "早起", "健康", "图书馆")
PROJECT = ("发版", "部署", "施工单", "接口", "页面", "功能", "模块", "仓库",
           "push", "tag", "release", "智能旅行", "travel", "learnsys",
           "学习工作台", "agent 中枢", "codex", "claude", "ssh", "ui",
           "地图", "preference-system", "trip", "偏好系统", "定位链路",
           "校对", "deepseek", "调研")
GENERIC = ("用户是一名大学生", "用户是大学生", "用户是一名学生")
PREFERENCE = ("偏好", "习惯", "希望", "喜欢", "要求", "目标", "需要", "倾向")
# 这些词说明讲的是「学习系统这个产品 / 工程项目」，不是用户自己的学习画像。
PRODUCT = ("学习系统", "学习工作台", "工作台", "平台", "插件", "题库",
           "施工单", "部署", "发版", "仓库", "接口", "页面", "模块", "功能",
           "监控", "agent", "UI", "重构", "架构", "每日积累", "重点词",
           "修复", "会话历史", "搜索框", "改代码")
# 只有真正的学习行为词，才允许把 project:* 救回 global。
RESCUE_LEARN = ("学习", "复习", "做题", "笔记", "听力", "六级", "英语",
                "算法", "数据结构", "课程", "考试", "刷题", "背诵",
                "写作", "翻译", "阅读", "口语")
# 已有记忆覆盖的元规则：不再重复留候选。
COVERED = ("先讨论方案", "天生一份", "长远角度", "重复说", "当场记录",
           "原题和答案", "一律用中文", "不要直接改代码", "记忆系统")


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").lower())


def _bigrams(text: str) -> set[str]:
    value = _norm(text)
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _similar(left: str, right: str) -> float:
    a, b = _bigrams(left), _bigrams(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def _project_scope(scope: str) -> bool:
    return str(scope or "").startswith("project:")


def _classify(row: dict, active: list[str], kept: list[str]) -> tuple[str, str]:
    content = row["content"]
    scope = row["scope"]
    if row["kind"] == "project":
        return "drop", "project_kind"
    if any(content == item for item in GENERIC):
        return "drop", "generic_identity"
    if any(phrase in content and any(phrase in item for item in active)
           for phrase in COVERED):
        return "drop", "covered_by_active"
    if any(word.lower() in content.lower() for word in PROJECT):
        return "drop", "project_state"
    if any(word.lower() in content.lower() for word in PRODUCT):
        return "drop", "product_state"
    if _project_scope(scope):
        # 模型把「leetcode / algorithm-notes」这类学习话题也标成项目；救回来。
        if (any(word in content for word in RESCUE_LEARN)
                and not any(word.lower() in content.lower() for word in PROJECT)):
            return "keep_global", "rescued_topic_scope"
        return "drop", "project_scope"
    if (("LLM" in content or "模型" in content)
            and not any(word in content for word in PREFERENCE)):
        return "drop", "technical_trivia"
    if any(_similar(content, item) > 0.72 for item in active):
        return "drop", "duplicate_active"
    if any(_similar(content, item) > 0.72 for item in kept):
        return "drop", "duplicate_candidate"
    if not any(word in content for word in LEARN + LIFE):
        return "drop", "not_learning_profile"
    if "教材" in content and "正在学习《" in content:
        return "drop", "course_content"
    if content.startswith("用户正在学习") and not any(
            word in content for word in PREFERENCE):
        return "drop", "transient_course"
    if ("核心是" in content and content.startswith("用户认为")
            and not any(word in content for word in PREFERENCE)):
        return "drop", "technical_trivia"
    return "keep", "learning_profile"


def _classify_diary(row: dict) -> tuple[str, str]:
    content = row["content"]
    if content.startswith(("答：", "从你的描述来看")) or "你整个学期" in content:
        return "drop", "ai_analysis"
    if any(word in content for word in ("vi是", "CSMA", "==", "单音节",
                                        "介词", "语法", "==have")):
        return "drop", "study_content"
    long_term = ("以后", "长期", "不再", "不要成为", "希望自己", "养成习惯")
    strong = any(word in content for word in long_term)
    # 日记正文里的时间戳 = 当天流水；长段落也基本是流水账。
    stamps = len(re.findall(r"\d{1,2}：\d{2}", content))
    if content.startswith(("这周", "本周", "下周", "今天", "明天")):
        return "drop", "transient_goal"
    if len(content) > 140:
        return "drop", "long_daily"
    if stamps >= 1 and not strong:
        return "drop", "daily_log"
    habit = (("每天" in content or "每周" in content)
             and stamps == 0 and len(content) <= 120)
    if not (strong or habit):
        return "drop", "not_long_term"
    return "keep", "diary_habit"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-diary", action="store_true",
                        help="同时整理日记与想法候选")
    parser.add_argument("--include-active", action="store_true",
                        help="同时复查已自动激活的档案事实")
    args = parser.parse_args()
    conn = store.connect()
    try:
        rows = store.list_memories(
            conn, limit=1000, status="candidate")
        allowed = {"archive_extract"}
        if args.include_diary:
            allowed |= {"diary", "idea"}
        rows = [row for row in rows if row.get("source") in allowed]
        if args.include_active:
            active_rows = [row for row in store.list_memories(
                conn, limit=1000, status="active")
                if row.get("source") == "archive_extract"]
            rows.extend(active_rows)
        active = [row["content"] for row in store.list_memories(
            conn, limit=1000, status="active")
            if row.get("source") != "archive_extract"]
        kept: list[str] = []
        counts: dict[str, int] = {}
        keep_rows, drop_rows = [], []
        for row in rows:
            if row.get("source") == "diary":
                action, reason = _classify_diary(row)
            elif row.get("source") == "idea":
                action, reason = "drop", "idea_meta"
            else:
                action, reason = _classify(row, active, kept)
            counts[reason] = counts.get(reason, 0) + 1
            if action.startswith("keep"):
                kept.append(row["content"])
                keep_rows.append((row, action, reason))
            else:
                drop_rows.append((row, reason))
        print(f"候选 {len(rows)}；保留 {len(keep_rows)}；归档 {len(drop_rows)}")
        print("分类：", counts)
        print("\n--- 保留 ---")
        for row, action, reason in keep_rows:
            flag = "→global" if action == "keep_global" else ""
            print(f"  #{row['id']} {row['scope']}{flag} {row['content'][:90]}")
        print("\n--- 归档样本（每类 5 条）---")
        seen: dict[str, int] = {}
        for row, reason in drop_rows:
            if seen.get(reason, 0) >= 5:
                continue
            seen[reason] = seen.get(reason, 0) + 1
            print(f"  [{reason}] #{row['id']} {row['content'][:80]}")
        if args.apply and not args.dry_run:
            for row, action, _reason in keep_rows:
                if action == "keep_global" and row["scope"] != "global":
                    store.update_memory(conn, row["id"], row["content"],
                                        scope="global")
            for row, reason in drop_rows:
                conn.execute(
                    "UPDATE agent_memories SET status='archived', "
                    "archived_reason=?, updated_at=datetime('now','localtime') "
                    "WHERE id = ?", (f"curate:{reason}", row["id"]))
            conn.commit()
            print("\n已应用：保留为候选，其余归档（可恢复）。")
        elif not args.dry_run:
            print("\n未加 --apply，未改动。")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
