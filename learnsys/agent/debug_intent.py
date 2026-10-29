"""判断这一轮是不是「粘贴代码 + 问哪里错」的调试题。

**唯一判据**：路由（提档）、Agent（强制思考）、提示词（必须运行）、收尾（未验证标记）
都从这里取，别各写一份关键词表。

判据故意保守：
- 必须有代码迹象（`#include` / 代码围栏 / 常见语法），且至少 5 行；
- 必须有调试意图词（没过 / WA / 报错 / 错在哪 / 超时…）；
- 单独出现「错误」不算（普通知识问答也会说「错误」）。
"""
from __future__ import annotations

CODE_HINTS = (
    "#include", "```", "public static", "std::", "printf(", "cout<<",
    "cin>>", "scanf(", "def ", "class ", "function ", "=>", ";->",
)
DEBUG_WORDS = (
    "没过", "wa", "答案错误", "报错", "错在", "哪里错", "为什么错", "哪错",
    "段错误", "越界", "崩溃", "超时", "运行不了", "跑不了", "编译失败",
    "一组", "测试点", "样例", "oj", "不通过", "通不过", "输出不对",
)
# 「用户明确让我跑」——只用来决定 run_code 要不要再弹确认，不用来判断是不是调试。
RUN_WORDS = (
    "跑一下", "跑一遍", "跑几个", "跑个", "跑跑看", "运行一下", "运行代码",
    "执行一下", "执行代码", "编译一下", "编译看看", "测试用例", "帮我测",
    "测一下", "验证一下", "试一下",
)
# 长代码 + 这些「题目」特征，按调试题处理：先跑再下结论，而不是读完就断言。
TASK_WORDS = ("题目", "要求", "输入格式", "输出格式", "样例", "示例",
              "测试点", "提交", "判题")


def detect(message: str) -> dict:
    """返回 {code_debug, has_code, debug_words, run_requested, signals}。"""
    text = str(message or "")
    lower = text.lower()
    lines = text.count("\n") + 1
    hints = [item for item in CODE_HINTS if item.lower() in lower]
    has_code = bool(hints) and lines >= 5
    words = [item for item in DEBUG_WORDS if item in lower]
    run_words = [item for item in RUN_WORDS if item in lower]
    # 「这段代码有什么问题 / 看一下」也算调试意图，但必须是长代码块，避免误伤短片段。
    if not words and has_code and lines >= 15 and "问题" in text:
        words = ["问题"]
    # 贴了长代码 + 题目描述（输入/输出格式、样例…）：本质就是调试题。
    if not words and has_code and lines >= 15:
        task_hits = [item for item in TASK_WORDS if item in text]
        if len(task_hits) >= 2:
            words = ["题目"] + task_hits[:2]
    signals = hints[:3] + words[:3] + run_words[:2]
    return {
        "code_debug": bool(has_code and words),
        "has_code": has_code,
        "debug_words": words,
        "run_requested": bool(run_words),
        "signals": signals,
    }
