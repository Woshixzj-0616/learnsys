"""P25.2 学习写入工具实现：生词、复习评档、训练错题。

全部由 `CONFIRM_TOOLS` 把关；这里只负责参数校验、写库与中文结果。
"""
from __future__ import annotations

from learnsys import store
from learnsys.services import review as review_service
from .context import ToolContext


def _open(ctx: ToolContext):
    return store.connect(ctx.db_path)


def _normalized(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def add_vocab(word: str, meaning: str = "", phonetic: str = "",
              context: str = "", source: str = "agent", *,
              ctx: ToolContext) -> str:
    """加一个生词；同词只补空字段，新词明天进复习队列。"""
    word = " ".join(str(word or "").split())
    if not word:
        return "单词是空的，没有加进生词本。请给一个单词或短语。"
    source = source if source in ("agent", "cet6") else "agent"
    conn = None
    try:
        conn = _open(ctx)
        item, created = store.add_vocab(
            conn, word=word, meaning=str(meaning or ""),
            phonetic=str(phonetic or ""), context=str(context or ""),
            source=source)
    except Exception as exc:
        return f"生词本保存失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if created:
        meaning_part = f" — {item.get('meaning')}" if item.get("meaning") else ""
        return (f"已加进生词本（#{item['id']}：{word}{meaning_part}）。"
                "明天会出现在复习队列。")
    return (f"生词本里已有「{item.get('word') or word}」（#{item['id']}），"
            "这次只补了空字段，没有覆盖原来的释义。")


def delete_vocab(word: str = "", item_id: int = 0, *,
                 ctx: ToolContext) -> str:
    """删一个生词（复习卡一起删）；按 id 或精确词形定位。"""
    conn = None
    try:
        conn = _open(ctx)
        target = None
        if item_id:
            try:
                target = store.get_vocab(conn, int(item_id))
            except (TypeError, ValueError):
                return "item_id 不是整数，没有删除。"
            if target is None:
                return f"生词本里没有 #{item_id}，没有删除。"
        else:
            word = " ".join(str(word or "").split())
            if not word:
                return "要删哪个词？请给词形或 item_id。"
            items = store.list_vocab(conn, query=word, limit=50)["items"]
            exact = [item for item in items
                     if _normalized(item.get("word")) == _normalized(word)]
            if len(exact) == 1:
                target = exact[0]
            elif len(exact) > 1:
                shown = "、".join(f"#{item['id']}" for item in exact)
                return f"生词本里有多个「{word}」（{shown}），请用 item_id 指定。"
            else:
                near = "、".join(
                    f"{item.get('word')}(#{item['id']})" for item in items[:5])
                return (f"生词本里没有「{word}」，没有删除。"
                        + (f"相近的有：{near}。" if near else ""))
        deleted = store.delete_vocab(conn, int(target["id"]))
    except Exception as exc:
        return f"删除失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if not deleted:
        return "这个词已经不在生词本里了，没有删除。"
    return (f"已从生词本删除「{target.get('word')}」（#{target['id']}），"
            "它的复习卡也一起删了。")


def rate_review(item_type: str, item_id: int, rating: int, *,
                ctx: ToolContext) -> str:
    """给一张到期卡片评档；一次一张，id 必须来自读工具。"""
    item_type = str(item_type or "").strip().lower()
    if item_type not in ("wrong", "vocab"):
        return "只能复习错题（wrong）或生词（vocab），没有记录。"
    try:
        item_id = int(item_id)
        rating = int(rating)
    except (TypeError, ValueError):
        return "item_id / rating 不是整数，没有记录。"
    if rating not in (1, 2, 3, 4):
        return "评分只能是 1–4（1 忘了 / 2 模糊 / 3 记得 / 4 简单），没有记录。"
    kind = "错题" if item_type == "wrong" else "生词"
    conn = None
    try:
        conn = _open(ctx)
        result = review_service.review(conn, item_type, item_id, rating)
    except LookupError:
        return f"没有找到{kind} #{item_id}，没有记录。先确认编号对不对。"
    except ValueError as exc:
        return f"没有记录：{exc}"
    except Exception as exc:
        return f"评档失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    return (f"已给{kind} #{item_id} 评档：{result['rating_name']}，"
            f"下次复习 {result['next_review']}。")


def save_training_error(question: str, my_answer: str,
                        correct_answer: str = "", skill: str = "",
                        source: str = "writing", *, ctx: ToolContext) -> str:
    """把写作/翻译错误收进错题本；同题干 + 同写法只留一条。"""
    question = str(question or "").strip()
    my_answer = str(my_answer or "").strip()
    if not question:
        return "缺少原句或题目，没有收进训练错题。"
    if not my_answer:
        return "缺少你的写法（my_answer），没有收进训练错题。"
    source = source if source in ("writing", "translation") else "writing"
    kind = "写作" if source == "writing" else "翻译"
    fingerprint = store.wrong_fingerprint(question + "\n" + my_answer)
    conn = None
    try:
        conn = _open(ctx)
        item_id, created = store.add_wrong_item(
            conn, question=question, answer=str(correct_answer or ""),
            my_answer=my_answer, tags=str(skill or ""), source=source,
            source_id=f"train:{fingerprint}", auto=False)
    except Exception as exc:
        return f"训练错题保存失败：{exc}"
    finally:
        if conn is not None:
            conn.close()
    if created:
        return (f"已收进训练错题（#{item_id}，{kind}）。"
                "明天会出现在复习队列。")
    return (f"这条错误已经在错题本里（#{item_id}，{kind}），没有重复添加。")
