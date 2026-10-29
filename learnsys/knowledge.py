"""知识点类目与提示词规则（零依赖）。

只放常量、归一和提示词文本，供 `ask/`、`agent/`、`services/` 共用；
不要在这里碰数据库或 FastAPI。

类目按学科分组：英语 7 + 编程 5 + 兜底「其他」= 13 类。
`subject` 是分组的唯一来源；提示词与工具 schema 都走 `category_help()`，
不要再各拼一份名单。
"""
from __future__ import annotations

import re

# 类目种子版本：以后只给 knowledge_points 加行（不改表结构）就 +1。
# `core/db/connection.py` 用它判断已是最新版本的库要不要补种。
SEED_VERSION = 1

CATEGORIES = (
    {"name": "词汇", "kind": "vocab", "sort": 10, "subject": "english"},
    {"name": "语音", "kind": "phonetics", "sort": 20, "subject": "english"},
    {"name": "语法", "kind": "grammar", "sort": 30, "subject": "english"},
    {"name": "听力细节", "kind": "listening_detail", "sort": 40,
     "subject": "english"},
    {"name": "听力主旨", "kind": "listening_main", "sort": 50,
     "subject": "english"},
    {"name": "听力推断", "kind": "listening_inference", "sort": 60,
     "subject": "english"},
    {"name": "阅读", "kind": "reading", "sort": 70, "subject": "english"},
    {"name": "数据结构", "kind": "data_structure", "sort": 110, "subject": "cs"},
    {"name": "算法", "kind": "algorithm", "sort": 120, "subject": "cs"},
    {"name": "C/C++", "kind": "c_cpp", "sort": 130, "subject": "cs"},
    {"name": "计算机网络", "kind": "network", "sort": 140, "subject": "cs"},
    {"name": "操作系统", "kind": "operating_system", "sort": 150, "subject": "cs"},
    {"name": "其他", "kind": "other", "sort": 999, "subject": "other"},
)
CATEGORY_NAMES = tuple(item["name"] for item in CATEGORIES)
SUBJECTS = (("english", "英语"), ("cs", "编程"), ("other", "兜底"))

# 旧数据 / 模型偶尔跑偏时的同义词；只做保守归并，不猜。
# ASCII 别名按 casefold 匹配，所以这里统一写小写。
ALIASES = {
    # 英语（原有）
    "生词": "词汇", "单词": "词汇", "词汇量": "词汇",
    "连读": "语音", "发音": "语音", "听音": "语音", "语音辨识": "语音",
    "句法": "语法", "从句": "语法", "时态": "语法", "非谓语": "语法",
    "细节": "听力细节", "听力": "听力细节", "细节理解": "听力细节",
    "主旨": "听力主旨", "大意": "听力主旨", "中心思想": "听力主旨",
    "推断": "听力推断", "推理": "听力推断", "态度": "听力推断",
    "阅读细节": "阅读", "阅读理解": "阅读",
    # 数据结构
    "链表": "数据结构", "单链表": "数据结构", "双链表": "数据结构",
    "线性表": "数据结构", "顺序表": "数据结构", "数组": "数据结构",
    "栈": "数据结构", "队列": "数据结构", "树": "数据结构",
    "二叉树": "数据结构", "图": "数据结构", "哈希表": "数据结构",
    "散列表": "数据结构", "堆": "数据结构", "并查集": "数据结构",
    # 算法
    "排序": "算法", "查找": "算法", "二分": "算法", "递归": "算法",
    "分治": "算法", "贪心": "算法", "动态规划": "算法", "回溯": "算法",
    "复杂度": "算法", "时间复杂度": "算法", "空间复杂度": "算法",
    "最短路": "算法", "最小生成树": "算法", "bfs": "算法", "dfs": "算法",
    # C/C++
    "c语言": "C/C++", "cpp": "C/C++", "c++": "C/C++",
    "指针": "C/C++", "引用": "C/C++", "内存泄漏": "C/C++",
    "虚函数": "C/C++", "模板": "C/C++", "stl": "C/C++",
    "面向对象": "C/C++", "raii": "C/C++",
    # 计算机网络
    "网络": "计算机网络", "tcp": "计算机网络", "udp": "计算机网络",
    "http": "计算机网络", "https": "计算机网络", "ip": "计算机网络",
    "dns": "计算机网络", "协议": "计算机网络", "路由": "计算机网络",
    "子网": "计算机网络", "拥塞控制": "计算机网络", "三次握手": "计算机网络",
    "osi": "计算机网络", "socket": "计算机网络", "套接字": "计算机网络",
    "网络编程": "计算机网络",
    # 操作系统
    "进程": "操作系统", "线程": "操作系统", "死锁": "操作系统",
    "调度": "操作系统", "虚拟内存": "操作系统", "分页": "操作系统",
    "文件系统": "操作系统", "并发": "操作系统", "互斥": "操作系统",
    "信号量": "操作系统", "系统调用": "操作系统", "中断": "操作系统",
}
_ALIAS_LOOKUP = {str(key).casefold(): value for key, value in ALIASES.items()}

_SPLIT_RE = re.compile(r"[、,，;；\n]+")


def categories_by_subject() -> list[tuple[str, list[str]]]:
    """按 subject 分组返回 [(标签, 类目名列表)]；顺序由 CATEGORIES 决定。"""
    groups: list[tuple[str, list[str]]] = []
    for key, label in SUBJECTS:
        names = [item["name"] for item in CATEGORIES if item["subject"] == key]
        if names:
            groups.append((label, names))
    return groups


def category_help() -> str:
    """提示词与工具 schema 共用的类目说明：分组 + 同学科规则。"""
    groups = "；".join(
        f"{label}：{'、'.join(names)}"
        for label, names in categories_by_subject())
    return ("类目按学科分组，同一道题只能选同一学科的 1–3 个类目"
            "（英语题不选编程类目，编程题不选英语类目；"
            "跨学科题按主要问题选，不确定选「其他」）：\n  "
            + groups + "。")


def normalize_points(raw) -> tuple[list[str], str]:
    """把模型/旧 tags 的原始 token 归一到 13 类目。

    返回 `(names, source)`：source 为 `model` 表示至少识别出一个真实类目；
    `fallback` 表示一个都没识别，落到「其他」，不能计入 BKT 样本。
    """
    if isinstance(raw, str):
        tokens = _SPLIT_RE.split(raw.replace("\r", ""))
    elif isinstance(raw, (list, tuple, set)):
        tokens = []
        for item in raw:
            tokens.extend(_SPLIT_RE.split(str(item or "").replace("\r", "")))
    else:
        tokens = []
    names: list[str] = []
    for token in tokens:
        text = str(token or "").strip().strip("`'\"“”‘’（）()[]【】")
        if not text:
            continue
        name = text if text in CATEGORY_NAMES else _ALIAS_LOOKUP.get(text.casefold())
        if not name:
            # 「听力细节理解」这类带后缀的写法：按最长类目名包含匹配
            for candidate in sorted(CATEGORY_NAMES, key=len, reverse=True):
                if candidate in text:
                    name = candidate
                    break
        if name and name not in names:
            names.append(name)
    if not names:
        return ["其他"], "fallback"
    return names, "model"


def prompt_rules() -> str:
    """出题/批改/工具 schema 共用的格式契约。"""
    return f"""【知识点标注（必须遵守）】
- 每道题固定写成两部分：先以「【第N题】」开头写题干；题干结束后另起一行写「【知识点】A、B」。
- A、B 只能从下面 {len(CATEGORIES)} 个类目里选 1–3 个，必须原样照抄，用「、」分隔；
  {category_help()}
- 不要用同义词（如「单词」「链表」「死锁」「TCP」），不要写解释，不要重复类目；
  一题同时考多个方面时，选最核心的 1–3 个。
- 批改块里不要重复上一题的【知识点】；下一题的知识点只写在下一题的题块里。

【判分口径（必须遵守）】
- 批改的第一行只能是「【批改】正确」或「【批改】错误」。
- 只要不是完全正确（含部分正确、漏点、表述不完整），一律写「【批改】错误」。
- 先给对错结论，再另起一行讲原因。"""
