# P19 · BKT 接回学习闭环

> 2.15.0 的 BKT 只展示，不影响任何行为。本轮把它接成两条实际动作：
> **今天页告诉你练什么**、**测验优先考薄弱类目**。
> 不做 FSRS 排程改造，不做自动掌握/退休，不做参数学习。2026-10-23 开工，版本 2.16.0。

## 1. 范围

| # | 改动 | 落点 |
|---|---|---|
| 1 | 今天页「薄弱点」卡改读 BKT；没有可建模样本才回退到「最近一条未掌握错题」 | `server/routes_data/today.py::_today_actions` |
| 2 | 今日测验 prompt 注入「本轮重点」：优先出掌握度最低的 1–3 个类目；今天页跳转可指定一个 focus | `ask/study.py::build_quiz_question`、`server/routes_data/today.py::study_today` |
| 3 | 测验页读 `?focus=`，随请求带给后端，并在提示行显示 | `web/js/pages/quiz.js` |
| 4 | `totals.weakest` 补 `attempts`，供卡片文案 | `services/knowledge.py::attempt_stats` |

**资料出题不动**：从资料出题时资料本身是范围，强行注入薄弱类目会跑偏。

## 2. 口径（单一落点）

薄弱点只在 `services/knowledge.py` 定义一次：

- 候选 = `attempt_stats` 结果里 `mastery_ready=True` 且 **掌握度低于掌握线（默认 70%）** 的类目；
- 排序 = 掌握度升序 → 样本多者优先 → `sort` → `id`；
- 最多取 3 个；「其他」不建模，天然不参与；
- 新增纯函数 `weak_points(points, limit=3, below=0.7)`；
  `attempt_stats` 的 `totals.weakest` 用 `below=1.01`，保留「全部 ready 里最低」的展示语义
  （已经全部掌握时不算薄弱，但知识点页仍能看到最低的是谁）。
- 今天页只用 `weak_points(limit=1)`；全部掌握 → 不显示薄弱卡，回退错题。

今天页只消费结果，不自己判断薄弱：

- 有 `weak_points` → 卡：`title="薄弱点练一道 · 阅读"`、`detail="掌握度 17%，5 条答题"`、
  `href="#/quiz?focus=阅读"`、`label="练这类"`；
- 没有 → 保持现有「最近错的：…」，`href="#/quiz"`。

`focus` 白名单：只能是 `learnsys/knowledge.py::CATEGORY_NAMES` 里除「其他」以外的值；
其余（含空、超长、带标记的文本）一律忽略，不拼进提示词。

## 3. 接口

### `GET /api/today`

`actions` 的 `kind="weak"` 卡按第 2 节生成；其余字段不变。

### `GET /api/study/today?focus=阅读`

追加返回：

```json
{
  "weak_points": [{"id": 7, "name": "阅读", "mastery": 0.17, "attempts": 5}],
  "quiz_focus": "阅读"   // 非法或为空时是 ""
}
```

`quiz_prompt` 新增一段（仅当有内容时）：

```text
【本轮重点】
最近掌握度最低的类目：阅读 17%（5 条答题）、语法 32%（5 条答题）。
出题时优先覆盖这些类目；今天的记录里没有相关素材时，可以围绕同一主题延伸，但别硬凑。

本轮指定重点：阅读。5 道题里至少 3 道要考「阅读」。
```

**今天没有新记录时**（只有答题流水、没有窗口/转写/问答/训练/断点）：
prompt 开头改为「我今天没有新的学习记录；请按下面的重点类目出题。」，
第 2 条要求改为「围绕重点类目出通识自测题，别编造我今天学过什么」。
前端按钮在 `weak_points` 非空时仍可点，提示行写明「今天没有新记录，按薄弱类目「阅读」出题」。

### `GET /api/knowledge`

`totals.weakest` 追加 `attempts`（加法，不改旧字段）。

## 4. 测试（先必红）

新文件 `tests/test_p19_bkt_loop.py`：

1. `weak_points` 纯函数：空、仅「其他」、不足样本、排序并列、limit、已掌握（≥70%）不算薄弱。
2. `/api/today`：无 ready 样本 → 回退错题卡；造 5 错阅读 + 5 对词汇 → 卡指向阅读、
   href 带 `focus=阅读`、detail 有掌握度；全部掌握 → 不显示薄弱卡。
3. `/api/study/today`：有 ready 样本 → `weak_points` 与 prompt 含类目；`focus=语法` → prompt
   含指定重点；`focus=<script>` / `focus=其他` → 忽略，prompt 不含；无当天记录但有薄弱类目 →
   prompt 走「通识自测题」口径。
4. `build_quiz_question` 纯函数：无 weak/focus 时结果与 2.15.0 一致（不多出「本轮重点」）；
   有当天记录时仍写「别超纲」。
5. `totals.weakest.attempts` 存在，且全部掌握时仍返回最低类目。

## 5. 明确不做

- BKT 不参与 FSRS 间隔、到期日、自动掌握。
- 不按掌握度自动出题（未点「出题」不会自己跑）。
- 不做参数学习、遗忘衰减、置信区间。
- 资料出题不注入薄弱类目。
- 今天页不改布局；仍是三张卡上限。

## 6. 验收

- `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"`
- `node --test web/tests/context.test.mjs`、`quiz-parse.test.mjs`
- `.venv/Scripts/python.exe tools/arch_report.py --check`
- 8799 源码后台 + Chrome：造样本 → 今天页卡 → 点进测验 → 确认 hint 与 prompt 重点；
  答完 1 题确认答题流水照旧。**不在生产库造样本。**

## 7. 版本

- `learnsys/ask/__init__.py` → 2.16.0；`web/sw.js` → v16（quiz.js / today 页面逻辑变化）。
- 无 schema 变更；回滚到 2.15.0 不需要迁移。
