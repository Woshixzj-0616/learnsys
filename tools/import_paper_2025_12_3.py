"""导入 2025-12 第三套（写作 + 翻译）的纸面作答与 DeepSeek 批改。

数据来源：`D:\\Desktop\\deepseek.docx`（负责人提供）。
题库条目 `w25` / `t25` 已写进 `learnsys/train/content/`；本工具只负责把
两条提交记录、整句卡、错误卡和生词写进生产库。

默认只读预演；`--apply` 才写库，写前自动备份到 `D:\\学习系统\\`。
重复执行按 `prompt_id` 跳过，不会重复建提交（卡片本身也按内容去重）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys import config, store  # noqa: E402
from learnsys.services.train import submissions as service  # noqa: E402
from learnsys.train import content, review as train_review  # noqa: E402

PAPER = "2025-12-3"
WRITING_ID = "w25"
TRANSLATION_ID = "t25"

WRITING_TEXT = """The Competitive Word

With the development of Science and technology, our society has improved largely in various industries. However, it also led to great competition in whole our growing time. So, I'm writing to give some suggestions to confront these various chanllenges.

The most essential preparation is consolidating a firmly basis on your profession. If you don't have a broad knowledge, you couldn't confront to various changes flexibly and you will lose your competition. In our society, it's widely believed that competition is the right way to gain success, yet the fact remains that corporation maybe a more benefical ability for you. So, when you improve your abilities, you should know that competition is a vital toll to improve us altogether rather than beating others. What's more, you should learn how to corporate with others and then make great progress together.

Competition has two side. It con leads to bad social emotions. However, If we see competition as a way to improve us and corporate with others, we may have a positive. mindset to various challenges in our future."""

TRANSLATION_TEXT = (
    "Chinese people emphasize on the self-strong and self-independent morality "
    "which is deeply cultivated in Chinese culture, and is an important part for "
    "our survival and development. After the Revolution and Opening, China "
    "continue continuously harvests more strengthen scientific investment in "
    "pursuing self-strong and self-independent and then make consecutire breaks "
    "in many industries such as Information technology, artificial intelligence, "
    "navigation, and so on. 5G network covered the whole nation, remote medical "
    "developed rapidly, the using of electrical payment made advanced in earth, "
    "Changer grouping moon performed the obvious development of navigation. The "
    "self-strong and self-independent morality became a huge energy to improve "
    "the process of nationally modern change and encourage chinese people to "
    "struggle to fulfill the rejuvenation of China.")

WRITING_REVIEW = {
    "band": 8,
    "band_reason": (
        "三段式结构完整、字数达标，但未照抄给定首句，主体又偏到“竞争与合作”，"
        "语言上有多处用词和拼写错误；按 15 分制估 7.5–8.5，取 8 档。"),
    "off_topic": False,
    "dimensions": {"content": 2, "structure": 3, "language": 2, "idiomatic": 1},
    "errors": [
        {"type": "拼写", "severity": "严重", "quote": "chanllenges",
         "fix": "challenges", "why": "拼写错误，应为 challenges。", "gloss": "挑战"},
        {"type": "搭配", "severity": "严重",
         "quote": "consolidating a firmly basis",
         "fix": "consolidating a solid foundation",
         "why": "firmly 是副词，不能修饰 basis；搭配是 consolidate a solid foundation。",
         "gloss": "巩固扎实的基础"},
        {"type": "搭配", "severity": "严重",
         "quote": "confront to various changes", "fix": "confront various changes",
         "why": "confront 是及物动词，直接接宾语，不加 to。", "gloss": "面对各种变化"},
        {"type": "用词", "severity": "严重", "quote": "corporation",
         "fix": "cooperation",
         "why": "corporation 是“公司、企业”，你想表达的是“合作”cooperation。",
         "gloss": "合作"},
        {"type": "拼写", "severity": "一般", "quote": "benefical",
         "fix": "beneficial", "why": "拼写错误，应为 beneficial。", "gloss": "有益的"},
        {"type": "用词", "severity": "严重", "quote": "vital toll",
         "fix": "vital tool",
         "why": "toll 是“通行费、伤亡人数”，这里应是 tool“工具”。",
         "gloss": "重要工具"},
        {"type": "语法", "severity": "一般", "quote": "two side",
         "fix": "two sides", "why": "two 后面的可数名词用复数 sides。", "gloss": ""},
        {"type": "语法", "severity": "一般", "quote": "It con leads",
         "fix": "It can lead",
         "why": "情态动词后用动词原形，且缺少情态动词 can；应为 It can lead。",
         "gloss": ""},
        {"type": "用词", "severity": "严重", "quote": "corporate with others",
         "fix": "cooperate with others",
         "why": "corporate 是形容词“公司的”，动词“合作”是 cooperate。",
         "gloss": "与他人合作"},
        {"type": "标点", "severity": "建议", "quote": "positive. mindset",
         "fix": "positive mindset",
         "why": "positive 与 mindset 之间不应有句号。", "gloss": ""},
        {"type": "用词", "severity": "一般", "quote": "whole our growing time",
         "fix": "our whole lives",
         "why": "语序和搭配不自然，可改为 our whole lives。", "gloss": ""},
        {"type": "语法", "severity": "一般", "quote": "improve us",
         "fix": "improve ourselves",
         "why": "improve 后接反身代词，表示“提升自己”。", "gloss": ""},
    ],
    "priorities": [
        "开头没有逐字照抄题目给定首句，属于严重审题失误；下次先抄首句再写。",
        "主体偏题：题目问“如何准备”，却大写“竞争与合作的辩证关系”；每段都要落到具体准备行动。",
        "先改三处硬伤：corporation→cooperation、toll→tool、confront to→confront。",
    ],
    "rewrite_task": (
        "只改三处：① 开头逐字照抄给定首句；② 把 corporation 改为 cooperation、"
        "toll 改为 tool、confront to 改为 confront；③ 第三段删掉与“如何准备”"
        "无关的竞争/合作议论，换成一个具体准备行动。"),
}

TRANSLATION_REVIEW = {
    "band": 4,
    "band_reason": (
        "信息点基本覆盖，但逐句存在中式英语、术语误译、时态与词性错误，"
        "多处影响理解；按 15 分制估 4–5，取 4 档。"),
    "dimensions": {"coverage": 4, "accuracy": 1, "fluency": 1, "terminology": 1},
    "info_points": {"missing": ["ip11"], "notes": "信息点基本覆盖，但漏译“中国梦”。"},
    "alignment": [
        {"segment": 1, "quote": "Chinese people emphasize on the self-strong and self-independent morality which is deeply cultivated in Chinese culture,"},
        {"segment": 2, "quote": "and is an important part for our survival and development."},
        {"segment": 3, "quote": "After the Revolution and Opening, China continue continuously harvests more strengthen scientific investment in pursuing self-strong and self-independent"},
        {"segment": 4, "quote": "and then make consecutire breaks in many industries such as Information technology, artificial intelligence, navigation, and so on."},
        {"segment": 5, "quote": "5G network covered the whole nation, remote medical developed rapidly, the using of electrical payment made advanced in earth,"},
        {"segment": 6, "quote": "Changer grouping moon performed the obvious development of navigation."},
        {"segment": 7, "quote": "The self-strong and self-independent morality became a huge energy to improve the process of nationally modern change"},
        {"segment": 8, "quote": "and encourage chinese people to struggle to fulfill the rejuvenation of China."},
    ],
    "errors": [
        {"type": "搭配", "severity": "严重", "quote": "emphasize on",
         "fix": "uphold",
         "why": "emphasize 是及物动词，不能加 on；“崇尚”用 uphold / advocate 更准确。",
         "gloss": "崇尚"},
        {"type": "中式英语", "severity": "严重",
         "quote": "self-strong and self-independent", "fix": "self-reliance",
         "why": "生造词；“自强自立”的固定译法是 self-reliance。", "gloss": "自强自立"},
        {"type": "术语", "severity": "严重", "quote": "Revolution and Opening",
         "fix": "reform and opening-up",
         "why": "“改革开放”是 reform and opening-up，不是 revolution（革命）。",
         "gloss": "改革开放"},
        {"type": "语法", "severity": "严重",
         "quote": "China continue continuously harvests more strengthen scientific investment",
         "fix": "China has continuously increased investment in scientific research",
         "why": "一句出现 continue/harvests 双谓语，strengthen 是动词不能修饰 investment；应改为现在完成时。",
         "gloss": ""},
        {"type": "拼写", "severity": "严重", "quote": "make consecutire breaks",
         "fix": "make new breakthroughs",
         "why": "consecutire 拼写错误；“取得新突破”用 make new breakthroughs。",
         "gloss": "取得新突破"},
        {"type": "术语", "severity": "严重", "quote": "navigation",
         "fix": "aerospace engineering",
         "why": "“航天工程”是 aerospace engineering；navigation 是航海/导航。",
         "gloss": "航天工程"},
        {"type": "用词", "severity": "严重", "quote": "remote medical",
         "fix": "remote medicine",
         "why": "“远程医疗”是 remote medicine / telemedicine，medical 是形容词。",
         "gloss": "远程医疗"},
        {"type": "用词", "severity": "严重", "quote": "electrical payment",
         "fix": "electronic payment",
         "why": "“电子支付”是 electronic payment；electrical 是“电气的”。",
         "gloss": "电子支付"},
        {"type": "误译", "severity": "严重", "quote": "Changer grouping moon",
         "fix": "the Chang'e lunar exploration project",
         "why": "“嫦娥探月工程”是 the Chang'e lunar exploration project，属严重误译。",
         "gloss": "嫦娥探月工程"},
        {"type": "中式英语", "severity": "严重",
         "quote": "made advanced in earth", "fix": "leads the world",
         "why": "“全球领先”用 leads the world / is a global leader。", "gloss": "全球领先"},
        {"type": "用词", "severity": "严重", "quote": "huge energy",
         "fix": "a powerful driving force",
         "why": "“强大动力”用 a powerful driving force；energy 语感不对。",
         "gloss": "强大动力"},
        {"type": "用词", "severity": "严重",
         "quote": "improve the process of nationally modern change",
         "fix": "advance the country's modernization process",
         "why": "“现代化进程”是 modernization process；nationally modern change 搭配不成立。",
         "gloss": "现代化进程"},
    ],
    "priorities": [
        "先改四个高危术语：reform and opening-up、aerospace engineering、remote medicine、the Chang'e lunar exploration project。",
        "全篇时态统一：讲现状用一般现在时 / 现在完成时，不要通篇过去时。",
        "删掉字对字直译：self-strong、electrical payment、made advanced in earth 分别改成 self-reliance、electronic payment、lead the world。",
    ],
    "rewrite_task": (
        "只改三处：① 开头补 Since the reform and opening-up；② 四个术语改成标准译法；"
        "③ 全篇时态统一为现在时 / 现在完成时。"),
}

# 批改词条准入最多 4 词，这里补录被准入规则挡掉、但值得背的术语。
EXTRA_VOCAB = [
    ("self-reliance", "自强自立", "改译：self-strong and self-independent → self-reliance", "translation", TRANSLATION_ID),
    ("make new breakthroughs", "取得新突破", "改译：make consecutire breaks → make new breakthroughs", "translation", TRANSLATION_ID),
    ("the Chang'e lunar exploration project", "嫦娥探月工程", "改译：Changer grouping moon → the Chang'e lunar exploration project", "translation", TRANSLATION_ID),
    ("lead the world", "全球领先", "改译：made advanced in earth → leads the world", "translation", TRANSLATION_ID),
    ("modernization process", "现代化进程", "改译：nationally modern change → modernization process", "translation", TRANSLATION_ID),
    ("national rejuvenation", "民族复兴", "第四句：the Chinese Dream of national rejuvenation", "translation", TRANSLATION_ID),
    ("the Chinese Dream", "中国梦", "第四句漏译：the Chinese Dream", "translation", TRANSLATION_ID),
    ("be deeply rooted in", "深植于", "第一句：deeply cultivated in → be deeply rooted in", "translation", TRANSLATION_ID),
    ("cooperation", "合作", "改译：corporation → cooperation", "writing", WRITING_ID),
    ("tool", "工具", "改译：toll → tool", "writing", WRITING_ID),
    ("challenge", "挑战", "拼写：chanllenges → challenges", "writing", WRITING_ID),
    ("confront", "面对、应对", "搭配：confront various changes（不加 to）", "writing", WRITING_ID),
    ("consolidate", "巩固", "搭配：consolidate a solid foundation", "writing", WRITING_ID),
    ("beneficial", "有益的", "拼写：benefical → beneficial", "writing", WRITING_ID),
    ("mindset", "心态", "搭配：a positive mindset", "writing", WRITING_ID),
]


def _packs() -> tuple[dict, dict]:
    writing = content.pack("writing", WRITING_ID)
    translation = content.pack("translation", TRANSLATION_ID)
    if writing is None or translation is None:
        raise SystemExit("题库里找不到 w25 / t25，先确认内容 JSON 已更新")
    return writing, translation


def _reviews(writing: dict, translation: dict) -> tuple[dict, dict]:
    w = train_review.validate_writing(
        WRITING_REVIEW, WRITING_TEXT, writing,
        flags={"paper": PAPER, "source": "paper"})
    t = train_review.validate_translation(
        TRANSLATION_REVIEW, TRANSLATION_TEXT, translation,
        flags={"paper": PAPER, "source": "paper"})
    return w, t


def _existing(conn, prompt_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM train_submissions WHERE prompt_id = ? "
        "ORDER BY id DESC LIMIT 1", (prompt_id,)).fetchone()
    return int(row[0]) if row else 0


def _backup(db_path: pathlib.Path) -> pathlib.Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.name}.bak-{stamp}-真题导入")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _import_one(conn, *, kind: str, prompt_id: str, pack: dict, text: str,
                review: dict, score: float) -> int:
    row = service.create_submission(conn, kind=kind, prompt_id=prompt_id,
                                    mode="timed")
    sub_id = int(row["id"])
    service.patch_submission(conn, sub_id, text=text, duration_s=1800)
    store.update_submission(
        conn, sub_id,
        flags_json=json.dumps({"paper": PAPER, "source": "paper",
                               "docx": "deepseek.docx"},
                              ensure_ascii=False),
        content_version=str(pack.get("content_version") or ""))
    store.set_submission_review(conn, sub_id, band=review.get("band"),
                                review=review, result_id=0)
    service._store_cards(conn, store.get_submission(conn, sub_id) or {}, review)
    service.set_external_score(conn, sub_id, score)
    return sub_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args()

    writing, translation = _packs()
    w_review, t_review = _reviews(writing, translation)

    print("写作批改：", w_review["band"], "档，错误", len(w_review["errors"]),
          "条，卡片", len(w_review["cards"]), "张")
    print("翻译批改：", t_review["band"], "档，错误", len(t_review["errors"]),
          "条，整句卡", len(t_review["cards"]), "张，生词",
          len(t_review["vocab_cards"]), "条")
    print("写作卡片：")
    for card in w_review["cards"]:
        print("  -", card["question"])
    print("翻译卡片：")
    for card in t_review["cards"]:
        print("  -", card["question"][:90])

    if not args.apply:
        print("\n预演结束；加 --apply 才写库。")
        return 0

    db_path = pathlib.Path(config.db_path())
    backup = _backup(db_path)
    print("已备份：", backup)

    conn = store.connect(str(db_path))
    try:
        for kind, prompt_id, pack, text, review, score in (
            ("writing", WRITING_ID, writing, WRITING_TEXT, w_review, 8.0),
            ("translation", TRANSLATION_ID, translation, TRANSLATION_TEXT,
             t_review, 4.5),
        ):
            old = _existing(conn, prompt_id)
            if old:
                print(f"{prompt_id}: 已有提交 #{old}，跳过")
                continue
            sub_id = _import_one(conn, kind=kind, prompt_id=prompt_id, pack=pack,
                                 text=text, review=review, score=score)
            print(f"{prompt_id}: 已建提交 #{sub_id}，外部分数 {score}")

        for word, meaning, context, source, paper_id in EXTRA_VOCAB:
            store.add_vocab(conn, word=word, meaning=meaning, context=context,
                            paper_id=paper_id, source=source)
        print("补录生词：", len(EXTRA_VOCAB), "条（已存在的按词去重）")
    finally:
        conn.close()
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
