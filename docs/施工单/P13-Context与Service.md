# P13 · Context / Service 薄抽象

> 2026-10-21。闸门取消后直接开工。对应 `00-阶段总览.md` 的 P13。
> **原则：只把六级已经在用的东西收成接口，不预造通用层。** 接口先能用，形状边用边改。

## 1. 范围

| 切片 | 内容 | 用户可见 |
|---|---|---|
| A | 生词统一表 `vocab_items`：六级生词从 localStorage 进库 | 是：生词本读写/导出走服务端 |
| B | 通用结果资产 API：按 id / 条件读 `service_results` | 否：为「结果可重开」铺路 |
| C | `ContextSnapshot` 收口：前端构造器 + 问一问挂资料时发结构化上下文 | 是：问一问的上下文可被 Agent 结构化读取 |
| D | 最小服务目录 `/api/services`：列出可用服务并按 kind 分派 | 否：给 MCP / 外部客户端铺路 |

**不做**：模型路由、成本面板、MCP 服务器、FSRS、AnkiConnect、新页面、把旧接口全部重写。
旧接口（`/api/cet6/translate*`、`/api/cet6/analysis*`）保留；它们和服务层共用同一份实现，不做第二套逻辑。

## 2. 数据

### 2.1 `vocab_items`

```sql
CREATE TABLE IF NOT EXISTS vocab_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT NOT NULL,
    normalized  TEXT NOT NULL,              -- lower(trim)，查重键
    meaning     TEXT NOT NULL DEFAULT '',
    phonetic    TEXT NOT NULL DEFAULT '',
    context     TEXT NOT NULL DEFAULT '',   -- 首次出现时的句子
    paper_id    TEXT NOT NULL DEFAULT '',
    paper_title TEXT NOT NULL DEFAULT '',
    sentence    INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'cet6',  -- cet6 / ask / manual
    status      TEXT NOT NULL DEFAULT 'active',-- active / archived
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vocab_word ON vocab_items (normalized);
CREATE INDEX IF NOT EXISTS idx_vocab_recent ON vocab_items (status, updated_at DESC);
```

**与总览 §3.2 的差异（有意）**：总览写唯一键 `(word,paper_id,context_hash)`；
这里改为**按词全局去重**，与现有 localStorage 行为一致（工作台本来就是「生词本里已有」）。
`paper_id`/`context` 只记首次出现，不覆盖。以后要按上下文分卡片，再加 `vocab_occurrences` 表，
不在这里提前抽象。

### 2.2 不新增其他表

`service_results` 已够用；B 只加读取接口。

## 3. 接口

### 3.1 生词

```
GET    /api/vocab?query=&limit=&offset=&status=active
POST   /api/vocab                 {word, meaning?, phonetic?, context?, paper_id?,
                                   paper_title?, sentence?, source?}
PATCH  /api/vocab/{id}            {meaning?, phonetic?, status?}
DELETE /api/vocab/{id}            硬删除
POST   /api/vocab/import          {items:[{word, meaning, context, paper?, at?}]}
GET    /api/vocab/export.csv      CSV（UTF-8 BOM，Excel 直接打开）
```

- `POST` 返回 `{item, created}`；同词已存在时补空字段并 `created=false`，不报错。
- 列表返回 `{"items":[...], "count":n}`。
- 写接口一律 `require_token`；读接口也用令牌（本机同源页面自动带）。

### 3.2 结果资产

```
GET /api/results?kind=&target_type=&target_id=&scope=&limit=50
GET /api/results/{id}
```

返回 `results.to_public()` 的形状（隐藏 `input_json`，`content_json` 解析成 `content`）。

### 3.3 服务目录

```
GET  /api/services                 → {items:[{kind,description,mode,params}]}
POST /api/services/{kind}          → 同步服务直接返回；后台任务返回 {id,status}
```

首批 kind：

| kind | 复用实现 | 模式 |
|---|---|---|
| `translate` | `services/translate.py::translate` | 同步 |
| `translate_items` | `services/translate.py::translate_sentences` | 同步 |
| `cet6_analyze` | `services/analysis.py::submit` | 后台 |

分派只做**参数白名单校验**，不写业务逻辑；未知 kind 返回 404，参数不合法 400。

### 3.4 前端

- `web/js/context.js`：`buildSnapshot(fields)` 按九键白名单构造、截断、20KB 上限；
  `describeSnapshot(snapshot)` 返回中文一行摘要。
- 问一问挂资料时，`/api/agent/chat` 增加 `surface:"ask"` 与
  `context_snapshot:{surface:"ask",object_type:"material",object_id,title,surrounding,provenance}`。
  正文仍走 `material_id`（单一真源，不把几十万字塞进快照）。
- 六级工作台 `70-vocab.js`：HTTP 模式读写 `/api/vocab`；首次打开且服务端为空时，
  把 `listening_workbench_vocab_v1` 一次性导入；之后 localStorage 只读（不再写）。
  `file://` 模式行为不变。

## 4. 函数落点

| 层 | 文件 | 内容 |
|---|---|---|
| core/db | `learnsys/core/db.py` | `vocab_items` 建表与索引 |
| store | `learnsys/store.py` | `add_vocab` / `list_vocab` / `update_vocab` / `delete_vocab` / `import_vocab` |
| services | `learnsys/services/results.py` | `list_results` |
| services | `learnsys/services/catalog.py` | `catalog()` / `dispatch(kind,payload)` |
| routes | `learnsys/server/routes_vocab.py` | 生词 6 个接口 |
| routes | `learnsys/server/routes_results.py` | 结果资产 2 个接口 |
| routes | `learnsys/server/routes_services.py` | 服务目录 2 个接口 |
| app | `learnsys/server/app.py` | 注册三个 router |
| web | `web/js/context.js`、`web/js/pages/ask.js` | 快照构造与发送 |
| cet6 | `D:\cet6_tool\workbench_src\js\70-vocab.js`、`55-api.js` | HTTP 读写与迁移 |

## 5. 测试

- `tests/test_vocab.py`：同词去重、补空字段、列表搜索、改释义、删除、导入幂等、
  CSV 表头与 BOM。
- `tests/test_results_api.py`：按 id / 条件读、隐藏 input_json、404。
- `tests/test_services_api.py`：目录包含三个 kind；未知 kind 404；参数白名单；
  用 mock 证明分派调用的是服务层函数。
- `tests/test_context_client.py`（node）：`buildSnapshot` 白名单、截断、超 20KB 抛错。
  运行：`node --test web/tests/context.test.mjs`。
- 六级：`build_workbench.py --check` 通过；生词迁移在真实 HTTP 页面手工验证一次。

## 6. 验收

1. 后端测试全过（当前 368 + 新增）。
2. 六级生词：HTTP 页面加入一个词 → 刷新仍在 → `learning.db` 有行 → CSV 能导出；
   localStorage 旧数据首次打开自动进库。
3. 问一问挂资料提问 → `messages` 里 user 消息带 `context_snapshot`，Agent 能引用资料标题。
4. `/api/results/{id}` 能取回 P12 产生的分析结果。
5. `/api/services` 能列出三项，`POST /api/services/translate` 与旧接口结果一致。
6. 一个 commit，写明范围；不 push、不发版。

## 7. 风险

- 生词从 localStorage 迁到库后，`file://` 旧页面仍写 localStorage；两边会分叉。
  处理：HTTP 迁移后 localStorage 只读；`file://` 只作为旧入口，不再宣传。
- 服务目录只做最小分派，不做鉴权以外的限流；外部接入等 P15 MCP 再议。
- `vocab_items` 全局按词去重，同一词在不同试卷只留首次上下文；需要时再加 occurrences。
