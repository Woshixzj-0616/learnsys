"""三类批改提示词（唯一落点）。

约定：
- 只输出一个 JSON 对象，不输出 Markdown、代码围栏或解释。
- 评分只给**档位描述**，不给本题范文，避免范文反向抬高分数。
- 每条错误必须引用原文精确片段，后端会逐条核对，查不到就丢弃。
"""
from __future__ import annotations

from . import rubric

PROMPT_VERSION = "train-review-v2"

SYSTEM = (
    "你是严谨的中国大学英语六级（CET-6）评分员。"
    "你只输出一个合法 JSON 对象，不输出 Markdown、代码围栏或任何解释。"
)


def _band_lines() -> str:
    return "\n".join(
        f"- {label}：{desc}" for _, _, label, desc in rubric.BAND_TABLE)


def _dimension_rule(kind: str) -> str:
    names = (rubric.WRITING_DIMENSIONS if kind == "writing"
             else rubric.TRANSLATION_DIMENSIONS)
    return "、".join(f"{key}（{rubric.DIMENSION_NAMES[key]}）" for key in names)


def _error_schema(kind: str) -> str:
    type_hint = ("语法/搭配/用词/中式英语/拼写/标点/结构" if kind == "writing"
                 else "漏译/误译/语法/搭配/术语/中式英语")
    return (
        '{"type":"' + type_hint + '","severity":"严重|一般|建议",'
        '"quote":"学生原文里的精确片段","fix":"改成什么","why":"为什么"}')


def writing_review_prompt(pack: dict, text: str, hard: dict) -> str:
    flags = hard.get("flags") or []
    flag_lines = "\n".join(f"- {row['level']}：{row['message']}" for row in flags)
    return f"""【任务】给下面这篇六级作文定档并列出影响分数的错误。

【题目】
{pack.get('prompt_en') or ''}

【中文提示】
{pack.get('prompt_zh') or ''}

【要求】30 分钟，{pack.get('target_words', [150, 200])[0]}–{pack.get('target_words', [150, 200])[1]} 词。

【程序已检查到的事实】（只作参考，不要重复计算）
{flag_lines or "- 无"}

【学生作文】
{text}

【官方口径】总体印象评分：先定档，再在档内浮动；只给 0–15 的整数档。
{_band_lines()}

维度只做画像，不相加冒充官方分：{_dimension_rule('writing')}，每项 0–5 分。

【输出】只输出一个 JSON 对象：
{{
 "band": 11,
 "band_reason": "一句话说明为什么在这个档",
 "off_topic": false,
 "dimensions": {{"content":4,"structure":3,"language":3,"idiomatic":1}},
 "errors": [{_error_schema('writing')}],
 "priorities": ["最影响分数的 3 个点，按顺序"],
 "rewrite_task": "只改哪 3 处，其余不动的二稿任务",
 "template_flags": {{"ratio":0.0,"phrases":[]}}
}}

【铁律】
1. 每条错误的 quote 必须逐字出现在学生作文里，是连续片段；不要改写、不要加省略号或「……」。
2. 最多 12 条错误；只列真正影响分数的，不要为了凑数挑无关小错。
3. 只有整篇明显跑题才把 off_topic 设为 true。
4. 不要给本题范文，不要输出任何 Markdown。
"""


def translation_review_prompt(pack: dict, text: str, hard: dict) -> str:
    point_lines = "\n".join(
        f"- {row.get('id')}：{row.get('zh')}（应有信息：{row.get('en', '')}）"
        for row in pack.get("info_points") or [])
    term_lines = "\n".join(
        f"- {row.get('zh')} → {row.get('en')}" for row in pack.get("terms") or [])
    flags = hard.get("flags") or []
    flag_lines = "\n".join(f"- {row['level']}：{row['message']}" for row in flags)
    return f"""【任务】批改下面这篇六级汉译英，定档并指出漏译、误译与语言错误。

【中文原文】
{pack.get('source_zh') or ''}

【信息点清单】（评分用；缺哪个就把 id 放进 missing）
{point_lines}

【术语表】（术语译错时，错误的 type 写“术语”）
{term_lines}

【程序已检查到的事实】（只作参考）
{flag_lines or "- 无"}

【学生译文】
{text}

【官方口径】总体印象评分：先定档，再在档内浮动；只给 0–15 的整数档。
{_band_lines()}

维度只做画像：{_dimension_rule('translation')}，每项 0–5 分。

【输出】只输出一个 JSON 对象：
{{
 "band": 10,
 "band_reason": "一句话说明为什么在这个档",
 "dimensions": {{"coverage":3,"accuracy":3,"fluency":2,"terminology":2}},
 "info_points": {{"missing":["ip3","ip7"],"notes":"漏译了哪层意思"}},
 "alignment": [{{"segment":3,"quote":"学生译文里对应这段的连续片段"}}],
 "errors": [{_error_schema('translation')}],
 "priorities": ["最影响分数的 3 个点，按顺序"],
 "rewrite_task": "只改哪 3 处，其余不动的二稿任务"
}}

【铁律】
1. 每条错误的 quote 必须逐字出现在学生译文里，是连续片段；不要改写或加省略号。
2. 最多 12 条错误；优先漏译、误译、改变原意，再列语法/搭配。
3. missing 只能填上面清单里的 id；不要编造 id。
4. alignment 的 segment 是中文段落序号（从 1 开始，按原文顺序），每个段落最多一条；
   quote 必须逐字出现在学生译文里，对不上就不写。它只用于逐句对照，不参与评分。
5. 不要输出参考译文，不要输出任何 Markdown。
"""


def sentence_review_prompt(item: dict, text: str) -> str:
    points = "、".join(item.get("info_points") or []) or "（无）"
    return f"""【任务】批改下面这一句六级汉译英。只给单句结论，不打 15 分档。

【中文句子】
{item.get('zh') or ''}

【该句信息点】{points}

【参考译文】（学生提交后才会看到；用它判断意思是否到位，但不要把它当作唯一答案）
{item.get('reference') or ''}

【学生译文】
{text}

【输出】只输出一个 JSON 对象：
{{"conclusion":"准确|基本准确|有偏差|误译",
 "info_points":{{"total":2,"covered":1,"missing":["漏掉的中文信息"]}},
 "must_fix":[{{"quote":"学生译文里的精确片段","fix":"怎么改","why":"漏译/误译/语法/搭配/改变原意"}}],
 "suggestions":[{{"quote":"学生译文里的精确片段","fix":"更地道的写法","why":"更地道/更简洁/更书面"}}],
 "variants":["1–2 个可接受的不同译法"],
 "minimal_fix":"只改错误、保留学生原句结构的最小改动版",
 "idiomatic":"重新组织的更地道版"}}

【铁律】
1. 只有**漏译、误译、语法错、搭配错、改变原意**放进 must_fix；风格偏好放 suggestions。
2. 每条 quote 必须逐字出现在学生译文里；找不到就删掉这条，不要编造。
3. 参考译文不是唯一答案；学生译法正确但不同，不要判错。
4. 不要输出任何 Markdown 或额外解释。
"""
