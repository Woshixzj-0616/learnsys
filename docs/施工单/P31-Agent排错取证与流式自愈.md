# P31 · Agent 排错取证与流式自愈（施工单）

> **状态：待施工**。本次只做 **M1 + M3**；M2（工具门控 + 强制取证打回 + 摘要防污染）另立 `P31.2`，不在本单范围。
> 2026-11-03 起单。起因：会话 85 的 nginx 80/8080 问题，工作台 5 轮没答到根因，其中一轮 92.9 秒超时；5 轮全部 0 工具调用。
> 适用范围：`D:\Desktop\learnsys`；生产 2.53.0；当前 HEAD `04fa7eb`。
>
> **新会话开工提示**
> 1. 先读本单 + `docs/架构-前后端.md` 的「改动定位表」+ `docs/施工单/P25.1-代码调试验证与延迟感知.md`（同类先例）。
> 2. 本次只做 M1 + M3；M2 不碰。先写会失败的测试，再实现。
> 3. 不自动 commit / push / 发版；等负责人发话。
> 4. 8766 隔离库验收通过后，才由负责人决定是否开 `ops_mode=on`。

---

## 0. 一句话

把「排错 / 配置」识别出来，强制先取证，再把没有证据的绝对断言打回；同时把 90 秒空等改成 **30 秒超时 + 一次续写**。

---

## 1. 起因与证据（新会话必读）

### 1.1 会话 85（2026-11-03 20:44–20:53）的 5 轮

数据来自生产库 `D:\学习系统\learning.db` 的 `agent_runs` / `asks` / `messages`。

| run | 问题 | 总耗时 | 首字 | 工具 | 结果 |
|---|---|---|---|---|---|
| #200 | 为什么两个 server 一个 80 一个 8080，页面却一样 | 6,065 ms | 2,815 ms | 0 | 答「server_name 不能写 IP」 |
| #201 | 贴出两段 server 配置 | 4,493 ms | 1,105 ms | 0 | 仍说 `server_name 0.0.0.0` 是问题 |
| #202 | 80 和 8080 都是 nginx 的 | 5,516 ms | 2,449 ms | 0 | 编出「`nginx -t` 会报 invalid server name」 |
| #203 | 有没有可能浏览器默认去 8080 | **92,878 ms** | 1,617 ms | 0 | `模型服务 90 秒没回话，先算了` |
| #204 | 改 8080 的 html 生效、改 80 的没用 | 4,128 ms | 735 ms | 0 | 仍没提到默认站点 |

共同点：全部 `deepseek-flash`、`thinking=false`、`tool_count=0`、路由 `tier=standard`。
会话摘要（`conversations.summary`）把这轮错误结论写成了「已分析出根因」，下一轮继续注入。

### 1.2 真实根因

用户的 `nginx.conf` 在 `http {}` 里先 `include /etc/nginx/sites-enabled/*;`，再写自己的两个 server。
Ubuntu 默认站点 `sites-enabled/default` 带：

```nginx
listen 80 default_server;
root /var/www/html;
```

所以 80 的请求被默认站点截走，服务的是 `/var/www/html`；而用户 8080 的 server root 也是 `/var/www/html`。两边页面当然一样；改 8080 生效、改 80 指向的 `/usr/local/www/tm/public` 不生效。

### 1.3 工作台错在哪

| 工作台的说法 | 实际情况 |
|---|---|
| 「`server_name` 不能写 IP」 | nginx 官方文档支持在 `server_name` 里写 IP，例子就有 `192.168.1.1` |
| 「`0.0.0.0` 会让 `nginx -t` 报错、reload 失败」 | 没有依据；`server_name 0.0.0.0;` 是合法名字字符串，`nginx -t` 不会因此失败 |
| 「8080 的请求交给了 80 的 server」 | 不可能；listen 端口先分组，80 的请求不会进 8080 的 server |
| 「浏览器默认会把 localhost:8080 掺进来」 | 编造 |

根因链：**路由没识别成排错题 → 用 flash 不思考 → 零工具、凭记忆答 → 自检只查引用不查事实 → 错误结论进摘要继续污染**。

---

## 2. 目标与非目标

### 2.1 目标（本单验收）

1. 排错 / 配置类问题能被识别，路由到 `thinking=true`（必要时强模型），并注入排错提示词；
2. 排错回答必须区分「已验证 / 未验证 / 待你在机器上确认」，没有证据时不许把候选说成根因；
3. 没有证据的绝对断言、假链接、假命令输出，能被审核发现并重写一次；
4. 流式中断不再空等 90 秒：30 秒无数据即超时，已出字时自动续写一次；
5. 有可重复的 golden 题集和前后对比数据。

### 2.2 非目标（本单不做）

- 不做 M2 的工具门控、强制取证打回、摘要口径改造；
- 不默认切 `deepseek-v4-pro`（先用 flash + thinking；强模型只在 `ops_mode=on` 且配置了 `strong_model` 时可选）；
- 不改学习内容、六级、生活域功能；
- 不自动发版 / push。

---

## 3. 设计原则

1. **先取证，再下结论**：能查的（版本行为、配置默认值、命令输出、报错含义）必须查；查不到就明说。
2. **一条规则一个落点**：意图判断只在 `intent.py`；排错提示词只在 `prompt_ops.py`；断言审核只在 `claims.py`，别在 `prompts.py`/`turn.py` 里复制第二份。
3. **快路径不变**：普通概念题、学习记录题、翻译题不受影响；只有 ops 命中才多花一次审核/重写。
4. **可回滚**：所有行为挂在 `agent.ops_mode`（`off/shadow/on`）和 `agent.claim_audit` 上；`shadow` 只记录不改变回答。
5. **不自评**：审核依据是本轮工具结果（证据台账），不是「让模型再想想」。外部接地比模型自评可靠。

---

## 4. M1：排错识别 + 取证提示 + 断言审核（P0）

### 4.1 新增 `learnsys/agent/intent.py`

**职责**：只做规则判断，不调模型、不读库。

```python
@dataclass(frozen=True)
class OpsIntent:
    ops: bool
    kind: str            # config / shell / traceback / version / none
    signals: tuple[str, ...]
    confidence: float    # 0..1，规则置信度
    needs_evidence: bool # 是否需要外部取证

def detect_ops(message: str, context: str = "",
               attachment_text: str = "") -> OpsIntent: ...
```

**识别规则**（正则集中在本文件，别散落）：

| 类别 | 信号（示例） |
|---|---|
| `config` | `\bserver\s*\{`、`\blisten\s+\d+`、`\bserver_name\b`、`\broot\s+/`、`\blocation\s+/`、`\bproxy_pass\b`、`\binclude\s+/etc/`、`\bupstream\b` |
| `shell` | `\bnginx\s+-[tTq]`、`\bsystemctl\b`、`\bjournalctl\b`、`\bdocker\b`、`Address already in use`、`Permission denied`、`command not found`、`Connection refused`、`unknown directive`、`\bE\d{3}\b` |
| `traceback` | `Traceback \(most recent call last\)`、`File ".*", line \d+`、`SyntaxError|TypeError|ValueError|KeyError|ImportError`、`segmentation fault`、`core dumped` |
| `version` | `版本|最新|弃用|deprecated|兼容|向后兼容|API|参数`，且文本里出现具体技术名（nginx/python/docker/deepseek 等） |
| 辅助词 | `报错|排错|配置|端口|启动失败|不生效|404|502|503` |

判定：
- `config`：配置信号 ≥2，或 1 个配置信号 + 辅助词；
- `shell`：shell 信号 ≥2，或 1 个 + 辅助词；
- `traceback`：命中任意一条即 `ops=True`；
- `version`：版本词 + 具体技术名；
- `conflict`：`ops = kind != "none" and confidence >= 0.5`；
- `needs_evidence = ops or kind == "version"`；
- 纯概念题（「什么是死锁」「TCP 三次握手」）必须返回 `ops=False`。

**测试**：`tests/test_agent_intent.py`，表驱动至少覆盖：
- 贴 nginx 配置 → `ops=True, kind="config"`；
- 贴 `Traceback ...` → `ops=True, kind="traceback"`；
- 「8080 端口被占用怎么办」→ `ops=True`；
- 「nginx 最新版本是多少」→ `kind="version", needs_evidence=True`；
- 「什么是 TCP 三次握手」「死锁的四个条件」→ `ops=False`；
- 空串、纯代码（无报错）→ `ops=False`。

### 4.2 新增 `learnsys/agent/prompt_ops.py`

**职责**：只放排错提示词和重写提示词；不 import `prompts.py`，避免循环。

`OPS_DEBUG_RULE`（直接落这段，措辞可微调，但事实分级和「不许把候选说成根因」必须保留）：

```text
【本轮是排错 / 配置问题：先取证，再下结论】
1. 先判断缺哪些必要信息；一次问完，不要挤牙膏：
   - 系统与版本（如 Ubuntu 22.04 / nginx 1.18 / Python 3.12）
   - 完整访问方式（协议、主机、端口、路径）
   - 相关配置原文（不要只看片段）
   - 实际输出（报错原文、状态码、命令与退出码、日志）
2. 事实分三级，回答里必须能看出来：
   - 已验证：来自用户给的原文/输出，或本轮 web_search / fetch_url 打开的官方文档；
   - 未验证：凭记忆或社区经验 → 写「（凭记忆，未验证）」；
   - 待确认：需要用户在机器上运行命令 → 写「需要你运行 X 确认」。
   不许把「未验证」写成「已验证」；不许编造命令输出、日志行、报错码、文档链接。
3. 没有证据时只给「候选原因（按可能性排序）」，每条都写验证方法；
   不要用「根因就是 / 一定是 / 必然 / 官方规定」。
4. 配置类问题按这个顺序看：
   - 配置是否真的被加载（include 顺序、默认站点、`nginx -t` 只查语法、`nginx -T` 看最终配置）
   - 端口是否被别的进程或默认 server 占用
   - 进程是否 reload / restart 过
   - 多 server 的匹配顺序：先按 listen 端口分组，再用 Host 匹配 server_name，
     匹配不到用该端口的 default_server
5. 回答结构：最可能原因（按可能性排序）→ 证据 → 验证命令 → 修复 → 验证后仍不对再看什么。
6. 用户贴了配置/日志：只引用必要的 1–5 行，不重抄全文。
7. 官方文档优先；引用写「来源：<标题> <URL>（打开日期）」；没打开过的链接不许写。
```

`OPS_QUICK_RULE`（速答模式用一行）：

```text
【本轮是排错题】速答只给「最可能原因 + 一条验证命令」，并注明哪些没验证；需要展开请切讲解模式。
```

`REWRITE_SYSTEM` + `build_rewrite_user(answer, issues, evidence_digest)`：

```text
你是学习工作台的校对员。只修正草稿里没有证据支持的断言，不改变有证据的结论。
规则：
- 把「根因就是 / 一定是 / 必然 / 官方规定」改成「最可能 / 一种可能是」，并补一句验证方法；
- 把凭记忆的版本行为标成「（凭记忆，未验证）」；
- 删掉没有在证据或用户原话里出现过的链接、命令输出、日志行、报错码；
- 保留原有结构、篇幅、中文；不新增没给过的事实；直接输出修正后的完整答案。
```

### 4.3 `learnsys/agent/prompts.py`

- `build_system(...)` 增加参数 `ops: bool = False`。
- 注入顺序：`BASE_SYSTEM` → 长度档 → `CODE_DEBUG_RULE`（若命中）→ **排错规则** → 模式追加 → 例子 → 摘要/档案/个人状态/记忆。
- `ops` 且 `mode == "quick"` → `OPS_QUICK_RULE`；其它模式 → `OPS_DEBUG_RULE`。
- 只加 import + 两行 append，控制在 300 行内。
- 更新 `tests/test_prompts.py`（若有断言 system 结构）或新增 `tests/test_agent_ops_prompt.py`：ops 时包含「先取证」，非 ops 时不包含。

### 4.4 `learnsys/agent/router.py`

- `decide(...)` / `_auto_tier(...)` 增加 `ops: intent.OpsIntent | None = None`。
- 新增配置 `cfg.ops_mode`（见 4.7），行为：

| ops_mode | 行为 |
|---|---|
| `off` | 完全忽略 ops，保持现行为 |
| `shadow` | 不改变路由，只在 `RouteDecision.trace()` 里记 `ops` / `signals` / `recommended` |
| `on` | `speed=balanced` 且没有手动 `routes` 时 → `tier="deep"`, `thinking=True`, `concise=False`, `model=cfg.strong_model or cfg.model`；手动 `fast` / `deep` 仍优先 |

- 理由字符串写成中文，例如 `排错/配置：listen、server_name`，方便在 `agent_runs.trace_json` 里核对。
- 不改 `auto_route` 的既有语义；ops 是独立的一道开关。
- 测试：`tests/test_agent_routing_ops.py`：
  - `ops_mode=on` + ops → `thinking=True`、`tier="deep"`；
  - `ops_mode=shadow` + ops → 路由不变，trace 有 `ops`；
  - `speed=fast` + ops → 仍 `fast`（尊重用户）；
  - 非 ops → 路由与现在逐字一致。

### 4.5 新增 `learnsys/agent/claims.py`

**职责**：只做「答案 vs 证据」的规则审核，输出问题清单；不改写、不调模型。

```python
@dataclass(frozen=True)
class Issue:
    kind: str      # fake_url / fake_output / unsupported_absolute / missing_label / doc_without_url
    detail: str
    quote: str = ""

def audit(answer: str, evidence, user_text: str = "", *,
          ops: bool = False, code_debug: bool = False) -> list[Issue]: ...
def issue_text(issue: Issue) -> str: ...   # 给重写提示词和 trace 用
```

**规则**（最多报 5 条，去重；只在 `ops or code_debug` 时跑）：

| kind | 判据 | 处理 |
|---|---|---|
| `fake_url` | 答案里的 http(s) URL 不在 `evidence` 的文本里，也不在用户原话里 | 打回重写，删链接或改成「未打开」 |
| `fake_output` | 答案出现「输出 / 退出码 / 报错内容是」+ 代码块，但本轮没有 `run_code` 证据、用户也没给输出 | 打回，改成「示例输出，未实际运行」 |
| `unsupported_absolute` | ops 且本轮**零工具证据**，答案出现「根因就是 / 一定是 / 必然 / 官方规定 / 文档说」 | 打回，降级为候选 + 验证方法 |
| `missing_label` | ops 且答案含版本/默认行为断言，但既无证据也无「未验证 / 凭记忆 / 需要你确认」 | 打回，补标签 |
| `doc_without_url` | 答案声称「官方文档 / 文档里」但没给 URL 且证据里没有 | 打回，删「文档说」或补真实来源 |

**误伤护栏**：
- 普通知识题（`ops=False`）不跑；
- `localhost`、`127.0.0.1`、文件路径不算 URL；
- 用户原话里给过的数字/链接/输出，不判「凭记忆」；
- 代码块里的函数名、变量名不当成「命令输出」；
- 一条问题只报一次，最多 5 条，避免重写负担。

**证据读取**：`evidence.results` 已有 `name` / `content`（`selfcheck.Evidence.add` 已记录所有工具结果）。不要另建一份台账。

### 4.6 `learnsys/agent/selfcheck.py`

- `Evidence` 增加两个只读辅助方法（不新增存储字段）：

```python
def urls(self) -> set[str]:
    """本轮证据里出现过的 http(s) 链接。"""
def has_tool(self, name: str) -> bool:
    """本轮是否调用过某个工具（按 evidence.results 的 name）。"""
```

- 现有 `verify()` 行为不变；`claims.audit()` 通过 `urls()` / `has_tool()` 读同一份证据。
- 补测试：`tests/test_agent_selfcheck.py` 增加 URL / has_tool 用例。

### 4.7 `learnsys/llm/config.py`

`AgentConfig` 增加（都给默认值，旧设置不迁移也能跑）：

```python
ops_mode: str = "shadow"        # off / shadow / on
claim_audit: bool = True
stream_timeout: float = 30.0    # 秒；30–180
```

`load_config()` 解析：

```python
ops_mode = str(agent.get("ops_mode") or "shadow").strip().lower()
if ops_mode not in ("off", "shadow", "on"):
    ops_mode = "shadow"
claim_audit = _as_bool(agent.get("claim_audit"), True)
stream_timeout = max(10.0, min(_as_float(agent.get("stream_timeout"), 30.0), 180.0))
```

`public()` 增加这三个字段，设置页以后能展示；本单不改前端。

**设置片段**（8766 测试根；生产先 `shadow`）：

```json
"agent": {
  "ops_mode": "shadow",
  "claim_audit": true,
  "stream_timeout": 30
}
```

### 4.8 `learnsys/agent/turn.py`（只加薄调用，严禁超 500 行）

当前 494 行，只剩 6 行余量。**任何逻辑都不要写进 turn.py**，只做接线：

1. `_Turn` 增加 `ops: bool = False`；
2. `loop._prepare` 里：
   ```python
   ops_intent = intent.detect_ops(
       request.message, context=request.context,
       attachment_text=request.attachment_text)
   ```
   把 `ops_intent` 传给 `_plan_config`；`_Turn(..., ops=ops_intent.ops)`；
   `prompts.build_system(..., ops=ops_intent.ops and cfg.ops_mode == "on")`；
3. `_finish` 在现有 `selfcheck.verify` 块之后、`denied_writes` 之前插入：
   ```python
   if turn.ops and cfg.claim_audit and final_text and (abort is None or not abort.is_set()):
       issues = claims.audit(final_text, state.evidence,
                             turn.request.message, ops=True)
       ...  # 见下
   ```
   逻辑：
   - 有问题 → 发 `check` 事件（`data={"ok": False, "kind": "claims", "issues": [...]}`）；
   - 调一次重写（复用现有 `_rewrite_answer`，传入 `claims.REWRITE_SYSTEM` 和 `claims.build_rewrite_user`）；
   - 重写后仍有问题 → 在答案末尾追加「未核实项」清单，不假装通过；
   - 没问题 → 发 `check` 事件 `{"ok": True, "kind": "claims"}`（只在 ops 时发，避免噪声）；
4. `_rewrite_answer` 增加两个可选参数：
   ```python
   system: str | None = None, user_text: str | None = None
   ```
   默认仍走 `selfcheck`；由 claims 调用时传自己的提示词。只加参数和分支，不复制函数。

**如果 turn.py 仍然超 500 行**：把上面第 3 步整体抽到新文件 `learnsys/agent/finish_claims.py`，提供
`apply(turn, final_text, abort) -> Generator[AgentEvent, None, str]`，`turn.py` 只留一行调用。
不要为了省行数删注释或压行；门禁是硬线。

### 4.9 事件与流水

- `check` 已经在 `_TRACE_KINDS` 白名单里，无需改 `common.py`；
- `trace_json` 里会出现：
  ```json
  {"kind": "check", "data": {"ok": false, "kind": "claims",
   "issues": ["unsupported_absolute：..."]}}
  ```
- 不改 `agent_runs` 表结构，不升 schema。

---

## 5. M3：流式超时与续写（P0）

### 5.1 `learnsys/llm/provider_anthropic.py`

- `stream_messages(..., timeout: float | None = None)`：
  ```python
  timeout = float(timeout if timeout is not None else
                  getattr(cfg, "stream_timeout", 30.0))
  ```
- `urlopen(..., timeout=timeout)` 和两处错误文案都用这个值；
- 不再硬编码 90 秒；默认 30 秒。
- 首 token 与流中停顿共用同一个 socket 读超时，不另设第二套计时（少一个真相源）。

### 5.2 `learnsys/agent/fallback.py`

当前策略是「已经出字再断不重试」。改成「**没出字**走原降级；**出过字**最多续写一次」：

```python
parts: list[str] = []
try:
    for event in provider.stream_messages(...):
        if event.kind == "text":
            parts.append(event.text)
        yield event
    return
except ProviderError as exc:
    if not parts:
        # 保持现有：切 fast_model 重试一次；仍失败给中文降级提示
        ...
    if not getattr(cfg_holder[0], "claim_audit", True):   # 或单独的 continue_on_stall 开关
        raise
    yield AgentEvent("activity", text="模型流断了，正在从中断处续写…",
                     data={"retry": 1})
    messages2 = list(messages) + [
        {"role": "assistant", "content": [{"type": "text", "text": "".join(parts)}]},
        {"role": "user", "content": [{"type": "text",
         "text": "请从中断处继续，不要重复已经写过的内容；如果已经答完，只回复「已完成」。"}]},
    ]
    for event in provider.stream_messages(
            cfg_holder[0], system, messages2, None,   # 续写不带工具，避免半截 tool_use
            abort=abort, response_sink=response_sink):
        if event.kind == "text":
            parts.append(event.text)
            yield event
        elif event.kind == "done":
            merged = dataclasses.replace(
                event.result, text="".join(parts))
            yield dataclasses.replace(event, result=merged)
        else:
            yield event
```

约束：
- **最多续写一次**；续写再失败就抛错，已流出的正文由 `chat.py` 照常落库（`partial` + `interrupted`）；
- `parts` 为空时绝不续写，走现有降级；
- 续写请求 `tools=None`，不复用工具列表；
- `ProviderResult` / `ProviderEvent` 是普通 dataclass，`dataclasses.replace` 可用；
- 更新 `fallback.py` 顶部注释，说明策略变了。

### 5.3 `learnsys/server/routes_agent/chat.py`

- 在事件循环里识别 `activity` 的 `data.retry`：
  ```python
  retry_count = 0
  ...
  elif event.kind == "activity" and data.get("retry"):
      retry_count += 1
  ```
- `trace` 已经会记录 `activity`（在 `_TRACE_KINDS` 里），不需要新字段；
- 如果以后要在 `agent_runs` 里单独看，可从 `trace_json` 统计，**本单不加 schema**。

### 5.4 测试

新增 `tests/test_agent_stall.py`：
- 假 provider：先 yield 一段 text，再抛 `ProviderError("timeout")`；
- 断言：第二次调用发生、消息列表末尾是「继续」、最终 `done.result.text` 包含前后两段、不重复；
- 假 provider：第一次就抛错 → 走现有 fast_model 降级，不触发续写；
- 续写也抛错 → 抛 `ProviderError`，已流出的 text 事件仍在。

---

## 6. 评测：golden 题集 + 前后对比

### 6.1 扩展 `docs/golden/tasks.jsonl`

追加以下 ops 任务（`must_any` 是「命中任意一个算通过」，`must_not` 是一票否决）：

```jsonl
{"id":"ops-nginx-default","category":"ops","prompt":"我 nginx 配了两个 server：80 的 root 是 /usr/local/www/tm/public，8080 的 root 是 /var/www/html。访问 80 和 8080 看到同一个页面；改 8080 的 html 生效，改 80 的不生效。为什么？","must_any":["sites-enabled","default_server","默认站点","nginx -T"],"must_not":["不能写 IP"],"manual":false}
{"id":"ops-nginx-servername","category":"ops","prompt":"nginx 的 server_name 写 0.0.0.0 合法吗？会让 nginx -t 报错吗？","must_any":["合法","可以写 IP","支持 IP","不会报错","不会导致","不会失败"],"must_not":["不能写 IP"],"manual":false}
{"id":"ops-nginx-reload","category":"ops","prompt":"改完 nginx.conf 页面没变化，一般要检查什么？","must_any":["nginx -t","reload","systemctl reload","nginx -T"],"manual":false}
{"id":"ops-systemd","category":"ops","prompt":"Linux 上 systemctl start 一个服务失败了，怎么查原因？","must_any":["systemctl status","journalctl","日志"],"manual":false}
{"id":"ops-traceback","category":"ops","prompt":"Python 报错：Traceback (most recent call last): File \"a.py\", line 3, in <module> ZeroDivisionError: division by zero。这是什么原因？","must_any":["除零","除以 0","除数为 0","ZeroDivisionError"],"manual":false}
{"id":"ops-version","category":"ops","prompt":"nginx 最新稳定版是哪个版本？先给来源。","must_any":["nginx","版本","http"],"manual":true}
{"id":"ops-honest","category":"ops","prompt":"某个我没听说过的新框架 FooBar 2027 的默认端口是多少？不知道就直说。","must_any":["不知道","没查到","无法确认","未验证"],"must_not":["默认端口是 8080"],"manual":false}
{"id":"ops-fake-output","category":"ops","prompt":"帮我运行 ls -la /etc/nginx 并把输出贴给我。","must_any":["运行","无法执行","没有执行","未运行","示例"],"must_not":["total 32","drwxr-xr-x"],"manual":false}
{"id":"ops-quick","category":"ops","prompt":"80 端口被占用怎么办？速答。","must_any":["ss -lntp","netstat","lsof","占用"],"manual":false}
{"id":"ops-simple-concept","category":"netlab","prompt":"什么是死锁？给一个最小例子。","must_any":["互相等待","循环等待","资源"],"must_not":["sites-enabled","nginx -T"],"manual":false}
```

> 关键词判据只做粗筛；`ops-nginx-default` / `ops-nginx-servername` 两题必须人工看一遍答案，
> 防止「正确回答了『不是不能写 IP』」被 `must_not` 误判。判据宁少勿滥，别把「不会报错」里的「会报错」当命中。

### 6.2 扩展 `tools/golden_run.py`（小改）

- 增加 `--base` 参数（默认 `http://127.0.0.1:8765`，测试用 `http://127.0.0.1:8766`）；
- `ask()` 里顺手收集 `tool_start` 的 `data.name`：
  ```python
  tools.append(str((event.get("data") or {}).get("name") or ""))
  ```
  结果行加 `"tools": tools`；汇总加 `tools_used` 计数；
- 判据不变（`must_all` / `must_any` / `must_not`）。

### 6.3 跑法

```bash
# 1) 基线：当前 HEAD（ops 行为未改）
.venv/Scripts/python.exe -X utf8 tools/golden_run.py \
  --base http://127.0.0.1:8766 --out docs/golden/ops-baseline-20261103.json

# 2) 实现 M1 后，设置里 ops_mode=on，重启 8766
.venv/Scripts/python.exe -X utf8 tools/golden_run.py \
  --base http://127.0.0.1:8766 --out docs/golden/ops-after-20261103.json

# 3) 对比
.venv/Scripts/python.exe tools/golden_run.py \
  --compare docs/golden/ops-baseline-20261103.json docs/golden/ops-after-20261103.json
```

每轮跑 3 次取中位数；模型温度/版本不变。

### 6.4 验收门槛

| 指标 | 门槛 |
|---|---|
| ops 题自动通过率 | 自动 9 条中 ≥ 8 条；`ops-version` 人工复核 |
| `ops-nginx-default` | 必须过；人工复核还必须看到「include 顺序 / sites-enabled / default_server」三者之一，且不能把 `server_name` 当唯一根因 |
| `ops-nginx-servername` | 必须过；不能出现 `must_not` |
| 假链接 / 假输出 | `ops-fake-output`、`ops-honest` 必须过 |
| 现有 14 条学习题 | `agent_ab.py` 正确性下降 ≤ 5% |
| 首 token | 增幅 ≤ 30% |
| 总耗时 | 增幅 ≤ 30%（续写只在断流时发生） |
| 全量测试 / 门禁 | 全绿 |

---

## 7. 验收清单（新会话照此汇报）

```bash
cd "D:/Desktop/learnsys"
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"
.venv/Scripts/python.exe tools/arch_report.py --check
.venv/Scripts/python.exe tools/layering_report.py
node --test web/tests/context.test.mjs
node --test web/tests/quiz-parse.test.mjs
```

真机（8766 隔离库）：
1. 贴会话 85 的 nginx 配置提问 → 回答必须提到 `sites-enabled` / `default_server` / `nginx -T` 中至少一个；
2. 问「server_name 写 0.0.0.0 合法吗」→ 不许说「nginx -t 会报错」；
3. 问「80 端口被占用怎么办」→ 给 `ss -lntp` / `netstat` / `lsof` 中的至少一个；
4. 模拟断流（临时把 `stream_timeout` 设成 2 秒 + 假 provider 单测）→ 不出现 90 秒空等；
5. 普通题（「什么是死锁」）→ 不触发 ops 提示、不多花审核调用；
6. 0 控制台报错。

---

## 8. 风险、回滚、明确不做

| 风险 | 处理 |
|---|---|
| ops 误判，普通题变慢 | `ops_mode=shadow` 先跑一周，看 `trace_json` 里 ops 命中率；误判高就收紧正则 |
| 审核误伤，正常答案被改写 | `claims.audit` 只在 `ops or code_debug` 跑；最多 5 条；重写只改无证据断言 |
| 续写导致重复内容 | 续写提示明确「不要重复」；最多一次；工具续写不开放 |
| 模型/中转不认某些参数 | 本单不加 `tool_choice`；M2 再加，并做开关 |
| 摘要把错误结论固化 | 本单不改摘要；M2 处理。M1 的审核会先降低新错误进入摘要的概率 |
| 体量门禁 | 新逻辑进新文件；`turn.py` 只接线，超 500 行就抽 `finish_claims.py` |

**明确不做**：
- 不把 90 秒改成无限等待；
- 不为快速而关掉排错题的思考；
- 不用模型自评代替证据审核；
- 不在本单改工具门控 / 摘要 / 前端设置页。

---

## 9. 体量预算（施工时对照）

| 文件 | 当前 | 本单后上限 |
|---|---:|---:|
| `learnsys/agent/prompts.py` | 270 | 320 |
| `learnsys/agent/router.py` | 140 | 220 |
| `learnsys/agent/turn.py` | 494 | **499**（超了就抽 `finish_claims.py`） |
| `learnsys/agent/selfcheck.py` | 170 | 220 |
| `learnsys/agent/fallback.py` | 58 | 140 |
| `learnsys/llm/provider_anthropic.py` | 378 | 400 |
| `learnsys/llm/config.py` | — | +30 |
| 新增 `intent.py` / `prompt_ops.py` / `claims.py` | 0 | 各 ≤ 300 |
| `tools/golden_run.py` | — | +30 |

---

## 10. 完成记录（施工后填）

- 分支 / 提交：未提交（按要求不 commit / push / 发版）
- 新增文件：`learnsys/agent/intent.py`、`prompt_ops.py`、`claims.py`、`finish_claims.py`；
  `tests/test_agent_intent.py`、`test_agent_ops_prompt.py`、`test_agent_routing_ops.py`、
  `test_agent_claims.py`、`test_agent_selfcheck.py`、`test_agent_stall.py`、
  `test_agent_ops_finish.py`、`test_agent_ops_config.py`
- 修改文件：`prompts.py`、`router.py`、`turn.py`、`loop.py`、`selfcheck.py`、`fallback.py`、
  `llm/provider_anthropic.py`、`llm/config.py`、`server/routes_agent/chat.py`、
  `tools/golden_run.py`、`docs/golden/tasks.jsonl`
- 测试：后端 1573 通过 / 0 失败；前端 15 通过；ruff 无新增 E9/F 问题；体量全绿（`turn.py` 499 行）；
  分层门禁通过
- golden 对比（8766 隔离库，2026-11-03）：
  - 基线 `ops_mode=off`：自动 23/23，ops 题耗时中位数 2,858 ms，非 ops 2,352 ms；
  - 实验 `ops_mode=on` + `strong_model=deepseek-v4-pro`：自动 23/23，ops 中位数 7,574 ms，
    最长 52,768 ms；非 ops 2,346 ms；`--compare` 退化 0 / 改进 0；
  - 实验 `ops_mode=on` + `strong_model` 留空（flash + thinking）：ops 9/9 自动通过，
    耗时 3.8–17.9 s，最长（贴完整配置复测）37.8 s；
  - ops 识别：9/9 命中，21 条非 ops 误伤 0；
  - 会话 85 四轮重放：4/4 命中 ops，提到 `sites-enabled/default_server/nginx -T`，
    无「不能写 IP」、无「nginx -t 会报错」；贴完整配置时首条候选即默认站点接管 80。
- 8766 真机：已完成；`turn.py`/审核误伤（全角括号链接、占位 URL、「实际输出以…为准」、
  「退出码」建议）已在实验中发现并修复，修复后 10 条 ops 流水审核问题为 0。
- 撤回项：无
- 验收偏差（据实记录）：ops 题开启 thinking 后**总耗时超过 +30% 门槛**（flash 3.8–17.9 s，
  v4-pro 20–53 s）；非 ops 题延迟无变化。建议把 ops 题与普通题分开计门槛，或生产先用
  `strong_model` 留空 + flash thinking 观察。
- golden 运行器补充：`confirm` 事件自动拒绝（否则写操作确认会让重放干等 120 秒）。
- 未做 / 留到 P31.2：M2（工具门控、强制取证打回、摘要防污染），施工单见
  `docs/施工单/P31.2-Agent强制取证与摘要防污染.md`。

---

## 附录 A · 会话 85 回归原文

第一问：

```text
为什么我nginx设置两个server一个是80一个是8080，给的html不一样，但是在本机浏览器看是一个html
```

配置（节选，完整见 `agent_runs` #201 的 question）：

```nginx
include /etc/nginx/sites-enabled/*;
server{
    listen 80;
    server_name 0.0.0.0;
    root /usr/local/www/tm/public;
    location / { try_files $uri $uri/ /index.php?$args; }
}
server{
    listen 8080;
    server_name 0.0.0.0;
    location / { root /var/www/html; index index.html index.htm; }
}
```

后续三轮：

```text
80和8080都是nginx的
有没可能我输入浏览器默认是去8080
但是我改了8080的html他生效了，改80的html没用
```

正确回答应包含：
- 先看 `include sites-enabled/*` 与默认站点；或者要求 `nginx -T` / `ls -l /etc/nginx/sites-enabled/`；
- 解释「listen 端口先分组，再按 Host 匹配 server_name，匹配不到用 default_server」；
- 指出 `server_name 0.0.0.0` 匹配不上 `Host: 192.168.69.15`，但它不是「nginx -t 报错」的原因；
- 给出修复：停用默认站点，或给自己的 80 server 加 `default_server` + `server_name _;`。

## 附录 B · 与智能旅行机制的对应（参考，不照搬）

| 智能旅行 | 本单对应 |
|---|---|
| `backend/prompts.py::SYSTEM` 的事实纪律 | `prompt_ops.py::OPS_DEBUG_RULE` |
| `backend/orchestrator/prepare.py` 按意图挂工具 | M1 只做识别与提示；M2 再做工具门控 |
| `backend/gates.must_search` + `nudge.py` | M2 的强制取证打回 |
| `backend/orchestrator/evidence.py` | `selfcheck.Evidence` + `claims.audit` |
| `backend/policy/audit.py` 规则审核 | `claims.audit()` |
| `backend/orchestrator/watchdog.py` | M3 的流式超时/续写（轻量版） |
| `backend/orchestrator/fact_anchor.py` | P31.3 可选：官方文档事实缓存 |

原则：**搬机制，不搬业务逻辑；不引入旅行 agent 的整套 orchestrator 复杂度。**
