# P27 · 个人 AI 工作台（地基与默认入口）

> 2026-10-29 负责人拍板：工作台升级为**个人 AI 工作台**，可以辅助学习；生活数据进同一个库；
> 工作项目文档**只引用不复制**；阶段顺序由本文定；工作台作为**默认入口**。
> 本文是 P27 的施工单，附 P28–P31 概要。开工前先读 `docs/架构-前后端.md` 第 7 节「改动定位表」。

---

## 0. 一句话

先把「一个上下文内核 + 三域首页 + Agent 状态注入」做出来，让学习/工作/生活共用同一份状态；
不先做任何单一场景的深水功能。

**阶段顺序（已定）**

| 顺序 | 阶段 | 周期 | 为什么排这里 |
|---|---|---|---|
| 1 | **P27 地基** | 1 周 | 三域都要读同一份状态；没有它，后面每域都会长一套 |
| 2 | **P28 学习闭环** | 1–2 周 | 日常频率最高，当前闭环全空（0 卡/0 错题） |
| 3 | **P29 工作交接** | 1–2 周 | Codex 已有记忆基线，增量收益明确但不如学习紧迫 |
| 4 | **P30 生活助手** | 1–2 周 | 新表面多、频率低，可独立做，放后面 |
| 5 | **P31 统一与评测** | 持续 | 需要前四阶段的数据，过早做会空转 |

---

## 1. P27 目标（可验收）

1. 打开工作台，默认落在 `#/today`，一屏能看到**学习 / 工作 / 生活**三域状态。
2. 后端有一个唯一装配点 `services/home.py`，三域数据都从这里出。
3. Agent 每一轮自动拿到一段 ≤600 字的「个人状态」，**不依赖模型主动调工具**。
4. 新增 4 张表，只做加法迁移；生产库 `user_version 11 → 12`。
5. Web 与 Qt 今日页同步；现有今日页布局门禁仍然通过。

**不做**：复习卡写入（P28）、项目 HANDOFF 生成（P29）、订阅调度（P30）、跨源聊天索引（P31）。

---

## 2. 数据层（P27.1）

### 2.1 新表

新增 `learnsys/core/db/schema_personal.py`，按 `schema_briefing.py` 的写法导出 `PERSONAL_SCHEMA`，
在 `schema.py` 里拼到 `SCHEMA` 末尾；`SCHEMA_VERSION = 12`。

```sql
CREATE TABLE IF NOT EXISTS profile_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'preference', -- preference / goal / constraint
    content     TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT '',           -- 出处：会话/日期/用户原话
    confidence  REAL NOT NULL DEFAULT 0.5,
    status      TEXT NOT NULL DEFAULT 'active',     -- active / archived
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_kind ON profile_facts (kind, status);

CREATE TABLE IF NOT EXISTS project_refs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    repo_path    TEXT NOT NULL DEFAULT '',          -- 只存路径，不复制仓库内容
    handoff_path TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',    -- active / paused / archived
    next_step    TEXT NOT NULL DEFAULT '',
    risk         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'news',      -- news / word / price / stock / custom
    cadence      TEXT NOT NULL DEFAULT 'daily',     -- daily / weekly
    at_time      TEXT NOT NULL DEFAULT '07:30',
    sources_json TEXT NOT NULL DEFAULT '[]',
    last_run     TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (topic, kind)
);

CREATE TABLE IF NOT EXISTS daily_cards (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day          TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'life',      -- learn / work / life
    title        TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL DEFAULT '{}',
    read_at      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE (day, domain, title)
);
CREATE INDEX IF NOT EXISTS idx_daily_cards_day ON daily_cards (day, domain);
```

**不要**给 `events`、`agent_tasks`、`wrong_items` 加平行表；生活事件写 `events(module='life')`，
工作待办继续用 `agent_tasks`，学习任务继续用 `day_plan`。

### 2.2 store

新增 `learnsys/store/personal.py`：只放 SQL，路由和服务不写 SQL。
- `profile_facts`: `list_facts / upsert_fact / archive_fact`
- `project_refs`: `list_projects / upsert_project / set_next_step`
- `subscriptions`: `list_subscriptions / due_subscriptions / mark_run`
- `daily_cards`: `list_cards / upsert_card / mark_read`

### 2.3 迁移

- `SCHEMA_VERSION = 12`；`connect()` 版本不一致时跑建表，幂等。
- 测试必须用临时 `DATA_ROOT`（现有 `test_db_guard` 已强制）。
- 迁移后跑一次生产库只读回放：`PRAGMA user_version` 应为 12；旧表行数不变。

---

## 3. 服务层（P27.1）

新增 `learnsys/services/home.py`（**唯一装配点**）：

```python
def payload(conn, day: str = "") -> dict:
    """返回 {date, learning, work, life}；三域各自只调用既有 service/store。"""
```

- `learning`：直接复用 `services/today.py::payload` 里的学习字段（三格、到期复习、最近错题、六级断点），
  不要重新查一遍；必要时把 `today.payload` 拆出一个 `learning_summary(conn, day)` 供两边共用。
- `work`：`store.personal.list_projects()` + `store.agent_tasks_running()` / `queued`（已有 store）。
- `life`：`store.personal.list_cards(day, domain='life')` + `due_subscriptions()` + 今日生活事件（`events`）。

```python
def agent_state(conn, day: str = "") -> str:
    """给 Agent 的一段 ≤600 字状态：今日三格、到期复习、最近 3 条卡点、项目下一步、生活提醒。"""
```

**边界**：`services/home.py` 只装配，不新增业务判定；判定仍在 `day_plan`、`review`、`today_actions`。

---

## 4. 接口（P27.1）

新增 `learnsys/server/routes_data/home.py`（只鉴权 + 返回，禁止 SQL）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/home` | 三域首页数据；`services.home.payload` |
| GET | `/api/profile/facts` | 偏好/目标/约束列表 |
| POST | `/api/profile/facts` | 新增/更新一条 |
| POST | `/api/profile/facts/{id}/archive` | 归档 |
| GET | `/api/projects` | 项目引用列表 |
| POST | `/api/projects` | 新增/更新（只存路径与状态） |
| GET | `/api/subscriptions` | 订阅列表 |
| POST | `/api/subscriptions` | 新增/更新 |
| POST | `/api/subscriptions/{id}/run` | 手动跑一次（P30 再接调度） |

保留 `/api/today` 不动，避免破坏现有页面；`#/today` 前端改用 `/api/home`，
`#/ask`、`#/cet6` 等继续用各自接口。**不要**让 `/api/home` 和 `/api/today` 各写一套学习装配。

---

## 5. Agent 状态注入（P27.1）

### 5.1 数据流（不要制造 agent↔services 新环）

```
routes_agent/chat.py（路由层）
  → services.home.agent_state(conn, day)   # 生成 ≤600 字
  → AgentRequest.personal_state
  → loop._prepare
  → prompts.build_system(..., personal_state=...)
```

- `learnsys/agent/turn.py` 的 `AgentRequest` 增加 `personal_state: str = ""`。
- `learnsys/agent/prompts.py::build_system` 增加参数与一段固定标题：
  `【个人状态（本轮自动带入，不用再调工具核对）】`。
- 上限落在 `learnsys/context.py`：新增 `MAX_PERSONAL_STATE = 600` 与 `clip_personal_state(text)`，
  其它地方不得再写数字。
- **agent 包不得 import services**；如果发现需要，说明数据流放错了层。

### 5.2 内容顺序（固定，便于测试）

1. 今日学习三格：`已完成/3`，未达标的点出 1 个；
2. 到期复习数 + 最近 3 条卡点（只写题干前 40 字）；
3. 项目：最多 2 个，写「名字 · 下一步」；
4. 生活：今天要提醒的 1–2 条（订阅/待办/作息）；
5. 没有数据的域写「暂无」，不要编。

---

## 6. 首页（P27.2，Web + Qt）

### 6.1 Web

改 `web/pages/today.html`、`web/js/pages/today.js`、`web/css/today.css`：

- Hero 与简报不动；在 Hero 下加一行 `domain-grid`，三张紧凑卡（每张 ≤ 3 行）：
  - **学习**：`今日 1/3 · 到期复习 4`，第二行「最近卡点：…」；
  - **工作**：`进行中 2 · 待排队 1`，第二行「下一步：…」；
  - **生活**：`今日订阅 3 · 待办 2`，第二行「提醒：…」。
- 三张卡分别深链到 `#/review`（或 `#/cet6`）、`#/agents`（或 `#/projects`）、`#/life`（P30 前先到 `#/briefing`）。
- **页面高度红线**：在 1440×900 下整页高度不超过 **1900px**（2.43.0 是 1621px；加三卡允许 +250px）。
- 移动宽度下三卡纵向堆叠，不横向滚动。

### 6.2 Qt

按 2.43.0 的做法同步 `learnsys/ask/qt/today.py` + `today_widgets.py`：
三张卡用一行三个按钮/卡片，内容只放「标题 + 一行状态」，点击走已有深链。
如果本轮时间不够，**允许 Qt 只显示三域入口、不显示明细**，但必须与 Web 的入口一一对应，
并在 `tests/test_today_layout.py` 里写清这条口径。

### 6.3 默认入口

- Web 默认路由已是 `today`（`shell.js::parseRoute`），无需改。
- 桌面快捷方式、托盘「打开工作台」保持指向 `#/today`；不新增开机自启默认值。
- 如果用户点「打开工作台」时上次停在别的页，仍然回到 `#/today`（默认入口语义），
  在 `ask/desktop/web_service.py` 或前端启动处确认。

---

## 7. 测试与门禁（P27.3）

先写会失败的测试，再实现。提交前全部跑：

```bash
cd "D:/Desktop/learnsys"
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"
node --test web/tests/context.test.mjs
node --test web/tests/quiz-parse.test.mjs
.venv/Scripts/python.exe tools/arch_report.py --check
.venv/Scripts/python.exe tools/layering_report.py --check
```

新增测试建议：

| 文件 | 测什么 |
|---|---|
| `tests/test_schema_personal.py` | 12 版建表幂等；旧库升级后行数不变 |
| `tests/test_personal_store.py` | 4 张表 CRUD；订阅去重；卡片唯一键 |
| `tests/test_home_service.py` | 三域装配；空数据不炸；学习字段与 `today.payload` 一致 |
| `tests/test_agent_personal_state.py` | 注入 ≤600 字；顺序固定；agent 不 import services |
| `tests/test_today_layout.py` | Web/Qt 三域入口一一对应；页面结构门禁 |
| `tests/test_home_routes.py` | 鉴权、返回形状、路由层无 SQL |

---

## 8. 真机验收（P27.3）

1. 起 **8766** 测试实例，数据根隔离（不要连生产库）。
2. `#/today` 三张卡有数据；空数据时显示「暂无」，不报错。
3. 在 `#/ask` 问一个**不需要工具**的问题（例如「我今天该先做什么」），
   回答里能自然提到今日三格/到期复习/项目下一步中的至少两项 —— 说明状态注入生效。
4. 控制台 0 报错；整页高度 ≤1900px。
5. Qt 今日页截图：三域入口可见，点击能跳转。
6. 打包版不要求在 P27 发版；先跑源码版。

---

## 9. 完成定义（DoD）

- 测试全过 + 两个门禁全绿；
- `docs/架构-前后端.md` 第 7 节补三行：`/api/home`、`services/home.py`、`schema_personal.py`；
- `docs/施工单/00-阶段总览.md` 加 P27 一行与状态；
- 改动按批次提交（建议 3 个提交：schema/store、service/route/agent、Web+Qt）；
- **不 push、不发版**，等负责人发话；
- 汇报按「原目标兑现表 → 证据入口 → 待拍板」一页给出。

---

## 10. 风险与规避

| 风险 | 规避 |
|---|---|
| 今日页又变长 | 三卡每张 ≤3 行；高度红线 1900px；移动端纵向 |
| Qt 同步漏 | 结构门禁 + 截图验收；允许只放入口但必须一一对应 |
| agent↔services 新环 | 状态在路由层生成，agent 只收字符串；加 import 检查测试 |
| schema 迁移碰生产 | 只加法；测试隔离；升级前备份 `learning.db` |
| 三域数据各写一套 | 唯一装配点 `services/home.py`；其它地方只调它 |
| 生活数据隐私 | 默认本地；不上传；文档写明删除/导出方式 |

---

## 11. 后续阶段概要（P28–P31）

### P28 学习闭环
- **P28.1**：问答模式暴露「收进复习」工具；代码调试结束后主动提议一次（确认卡）；
  `wrong_items` 支持代码题字段（题干/代码/错误类型/关键用例）；保存后 `seed_review_states`。
- **P28.2**：`knowledge.py` 增加编程类目（数据结构/算法/C++/网络/操作系统），迁移只加行；
  旧数据归「其他」，不强行回填。
- **P28.3**：今日页「到期复习」卡；错题本支持代码题展示；复习页可直接 `run_code` 验证。
- 验收：3 次真实调试 → ≥3 张卡；到期 >0；复习完成 1 次；BKT 类目有样本。

### P29 工作交接
- **P29.1**：`#/projects` 页 + `project_refs` CRUD（只存路径/状态/下一步/风险）。
- **P29.2**：`HANDOFF.md` 生成器：读仓库文档 + 记忆，产出**只含指针和状态**的交接页；
  标明「自动生成，不手改」；默认写到 `D:\学习系统\projects\<name>\HANDOFF.md`，不写回仓库。
- **P29.3**：派活时把「目标/上下文/验收/禁忌」拼进任务 prompt（扩展现有 `compose_chain_prompt`）。
- 验收：三个项目各一张卡；新会话读 HANDOFF ≤2 分钟能开工；任务链带交接包。

### P30 生活助手
- **P30.1**：订阅中心：主题/频率/来源；复用简报 `scheduler_tick` 的模式；每天写 `daily_cards`。
- **P30.2**：生活事务箱：`life_items`（标题/到期/状态/备注）+ 每日提醒；作息/精力只做轻记录。
- **P30.3**：创作库：图像 prompt/风格预设/作品归档；从豆包导出文本导入。
- 验收：迁移 5 个豆包定时任务；连续 7 天送达；一件事务从建到归档；数据全本地。

### P31 统一与评测
- 跨源只读索引（DeepSeek/Codex/Claude/豆包）：只入 FTS 与摘要，不搬原文进上下文。
- 记忆分层：`profile_facts`（稳定）/ 项目档（跨周）/ 临时任务（当天）；旧的 `agent_memories` 逐步归位。
- 评测集：40–60 条真实问题，固定期望要点；`tools/agent_eval.py` 可回归。
- MCP 扩展：把学习/工作/生活读工具暴露给外部 agent（只读）。
- 验收：能搜到三个月前的概念；同一偏好只说一次；改动有基线对比。

---

## 12. 新会话启动提示（复制给新会话）

```
你在 D:\Desktop\learnsys 工作，先读：
1) docs/施工单/P27-个人AI工作台-地基.md
2) docs/架构-前后端.md 第 7 节「改动定位表」
3) docs/施工单/00-阶段总览.md 的架构约定
本轮只做 P27.1（schema/store/service/route/agent 注入），不要动 P28 的复习卡写入。
按 AGENTS.md 的规矩：先写失败测试，再实现；不 push、不发版；改完跑全量测试 + 两个门禁。
汇报按「原目标兑现表 → 证据入口 → 待拍板」一页给。
```

---

## 13. 拍板记录

- 2026-10-29：工作台升级为「个人 AI 工作台」，可辅助学习。
- 2026-10-29：生活数据进同一个库（本地优先，不上传）。
- 2026-10-29：工作项目文档只引用、不复制。
- 2026-10-29：阶段顺序由 Claude 定（P27 → P28 → P29 → P30 → P31）。
- 2026-10-29：工作台作为默认入口。
