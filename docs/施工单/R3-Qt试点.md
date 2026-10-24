# R3 · Qt 试点施工单（设置页）

> 前置：`docs/重构-方向-20261024.md`（R2 已完成，生产 2.20.2）。
> 本阶段只做**一个页面的 Qt 试点**，不替换 Web 工作台、不改后端、不改业务行为。
> 试点是独立入口，默认仍打开 Web；达标后才决定是否扩大。

## 0. 边界（先写死，防止做着做着变成全量重写）

**做：**

- 托盘新增「设置（Qt 试点）」，打开一个独立的 Qt 设置窗口。
- 复用现有 `127.0.0.1:8765` 的 HTTP API（`/api/settings*`、`/api/memory*`、`/api/modules`）。
- 设置页的全部字段与动作：文本模型、视觉模型、成本、热键、数据/备份、Agent 记忆、模块开关、保存/测试/备份。
- 自动化测试（offscreen Qt）+ 量化验收。

**不做：**

- 不改 `routes_settings.py` / `routes_memory.py` 的接口与校验；Qt 只是另一个客户端。
- 不替换 Web 设置页，不删 `web/js/pages/settings.js`。
- 不引入 QML；用 Qt Widgets。
- 不重做工作台侧栏/路由；试点窗口先独立存在。
- 不改 PWA、远程访问、MCP；它们继续走 HTTP。
- 不做富内容页（问一问 Markdown/KaTeX、六级、资料阅读）——第一轮不参加试点。

## 1. 基线（2026-10-24，2.20.2）

| 项 | 现状 |
|---|---|
| Web 设置页 | `web/pages/settings.html` 190 行 + `web/js/pages/settings.js` 292 行 |
| 后端 | `learnsys/server/routes_settings.py` 309 行；`routes_memory.py` 61 行 |
| 配置落盘 | `D:\学习系统\设置.json`，原子写；密钥只回掩码 |
| Qt 入口 | `learnsys/ask/app.py::AskApp`；托盘在 `learnsys/ask/desktop/tray.py` |
| 线程模型 | Qt 主线程 + FastAPI 后台线程（`server/app.py::serve_in_thread`） |
| 测试 | `unittest` + `QT_QPA_PLATFORM=offscreen`；无 `pytest-qt` |
| 分层门禁 | `ask` 可以导入 `server` / `services` / `agent`；Qt 窗口不反向被低层导入 |

## 2. 架构决定

### 2.1 Qt 是 HTTP 客户端，不是第二个后端

Qt 设置窗口**不直接调用** `routes_settings.py` 里的函数，也不自己读写 `设置.json`。
它和浏览器一样：`GET /api/health` 拿令牌 → `GET/POST /api/settings`。
这样校验、原子写、密钥掩码只有一份实现。

### 2.2 目录

```text
learnsys/ask/qt/
  __init__.py          # 包说明
  api.py               # ApiClient：QNetworkAccessManager + 令牌 + JSON/中文错误
  widgets.py           # Section / FieldRow / 状态标签等小控件
  style.py             # 试点用 QSS（不追求与 Web 主题完全一致）
  settings.py          # SettingsWindow：设置页本体
learnsys/ask/desktop/qt_pilot.py   # QtPilotMixin：单实例窗口、托盘入口
tests/test_qt_settings.py          # 窗口 + 假客户端
tests/test_qt_api.py               # 纯函数：错误文案、payload
```

### 2.3 令牌与端口

- 端口用 `AskApp._web_port`（8765 或 8766；复用外部后台时也有值）。
- 令牌不自己生成：`ApiClient.start()` 先 `GET /api/health`，取 `token`（和 `web/js/api.js` 同一口径）。
- 令牌只存内存，不写日志、不进 tooltip、不进异常文案。
- 服务没起来：窗口显示「本地服务没起来，点重试」，不阻塞主程序。

### 2.4 线程

`QNetworkAccessManager` 在 Qt 主线程异步发请求，回调走信号，**不另起线程、不阻塞界面**。
测试注入假客户端（`FakeApiClient`），不发真实网络请求。

### 2.5 密钥

- `QLineEdit` 用 `EchoMode.Password`。
- 输入框永远不回填明文；只显示 hint：`已保存在设置文件：••••3456（留空不改）` / `来自环境变量` / `未配置`。
- 保存时**空字符串不进 payload**；保存成功后清空输入框并重新 GET `/api/settings` 刷新掩码。

## 3. 分步施工

> 每一步单独提交、单独可回滚。每步做完先跑该步测试，再进下一步。

### R3.0 基线与功能清单

- 把第 4 节功能清单抄进 `docs/施工单/R3-验收记录.md` 的空表。
- 记录 Web 设置页基线：打开耗时、表单填完耗时、浏览器进程内存、包体大小。
- 记录 API 契约：`GET/POST /api/settings`、`/api/settings/test`、`/api/settings/backup`、`/api/memory*`、`/api/modules`。
- 验证：清单每条都能在 Web 设置页找到对应控件/动作。
- 提交：`R3.0 Qt 试点基线`

### R3.1 客户端骨架 + 空窗口

**目标**：证明 Qt 能拿到令牌并读到 `/api/settings`。

- 新增 `learnsys/ask/qt/api.py`：
  ```python
  class ApiClient(QtCore.QObject):
      ready = QtCore.Signal()
      failed = QtCore.Signal(str)
      def start(self) -> None: ...
      def get(self, path, on_ok, on_err=None) -> None: ...
      def post(self, path, body, on_ok, on_err=None) -> None: ...
      def delete(self, path, on_ok, on_err=None) -> None: ...
  ```
  错误文案对齐 `web/js/api.js::parseError`：403 →「本地令牌不对，关掉窗口重试；还不行就重启学习工作台」；其余取 `detail`。
- 新增 `learnsys/ask/qt/widgets.py`：`Section`（标题 + 说明 + 内容区）、`FieldRow`（label + control + hint）、`StatusLabel`。
- 新增 `learnsys/ask/qt/settings.py`：先只放一个 `QDialog`，显示「正在连接后台…」/「已连接：版本 x」。
- `app.py::main()` 支持 `--qt-settings`（开发用）：启动服务后自动打开窗口。
- 验证：
  - `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m unittest tests.test_qt_settings`
  - 源码运行 `python -m learnsys.ask.app --qt-settings`，窗口显示后端版本。
- 提交：`R3.1 Qt 客户端骨架`

### R3.2 只读渲染

**目标**：从 API 填满所有字段，但先只能看不能改。

- `SettingsWindow.load()` 并发拉三份数据：`/api/settings`、`/api/modules`、`/api/memory`。
- 按 Web 页面顺序建 section：文本模型 → Agent 记忆 → 成本估算 → 视觉模型 → 快捷栏 → 数据与备份 → 侧栏模块。
- 文本/数字/下拉框先 `setReadOnly(True)` / `setEnabled(False)`；记忆列表只读。
- 密钥 hint 用 GET 返回的 `*_set` / `*_mask` / `*_source` 组装。
- 验证（假客户端）：
  - 所有字段值 = 样例 JSON；`modules` 数量与 `/api/modules` 一致。
  - 密钥输入框为空，hint 含掩码尾号。
- 提交：`R3.2 Qt 设置页只读渲染`

### R3.3 文本 / 成本 / 视觉 / 热键编辑 + 保存

**目标**：核心表单可改可存。

- 控件映射：
  | 字段 | 控件 |
  |---|---|
  | base_url / model / fast_model / strong_model | `QLineEdit` |
  | auth_token / api_key | `QLineEdit`（Password） |
  | auto_route / speed | `QComboBox` |
  | currency | `QLineEdit`（maxLength 12） |
  | max_tokens | `QLineEdit` + `QIntValidator`（空 = 不传，保持 Web 语义） |
  | price_input / price_output / price_cache_read | `QLineEdit` + `QDoubleValidator`（空 = 不传） |
  | hotkey | `QLineEdit` |
- `collect()` 对齐 `settings.js::collect()`：空密钥不放进 payload；数字字段只放合法值。
- `save()`：POST → 成功后重新 `load()` → 显示 `restart_required` 提示 → 清空密钥输入框。
- dirty 标记：任意 `textChanged` / `currentIndexChanged` / `valueChanged` 置位，窗口标题加 `*`，底部显示「有改动还没保存」。
- 验证：
  - `collect()` 的 payload 与 Web 同字段一致；空 token/key 不出现。
  - 保存后第二次 GET 的掩码更新；热键保存后提示重启。
  - 后端 400（如 `hotkey=Q`）时窗口显示中文 `detail`，不弹裸异常。
- 提交：`R3.3 Qt 设置页核心表单`

**停点 1**：核心表单可用后，先在源码模式手动走一遍保存/重开；没问题再继续。

### R3.4 密钥语义专项

**目标**：把「只进不出、留空不改」锁死。

- 测试：
  - 保存两次：第一次填 `sk-test-123456`，第二次留空 → 设置文件里的 token 不变。
  - 任何日志/异常/窗口文本里不出现明文；只出现掩码。
  - `auth_token_source` 为 `env` 时 hint 显示「来自环境变量」。
- 验证：`tests/test_qt_settings.py` + 复用 `tests/test_web_v2.py` 的后端口径。
- 提交：`R3.4 Qt 设置页密钥语义`

### R3.5 测试连接 + 立即备份

**目标**：两个动作按钮与 Web 行为一致。

- 「测试文本连接」→ `POST /api/settings/test {"kind":"text"}`；「测试视觉连接」→ `kind:"vision"`。
- 有未保存改动时先提示「先保存再测：测试用的是已保存的配置」（对齐 Web）。
- 请求期间禁用按钮，显示「测试中…」；结果用绿色/红色状态标签。
- 「备份现在」→ `POST /api/settings/backup`；显示返回的路径/大小；完成后更新「最近备份」。
- 验证：假客户端分别返回成功/失败，按钮状态与文案正确。
- 提交：`R3.5 Qt 设置页测试与备份动作`

### R3.6 Agent 记忆 CRUD

**目标**：列表、添加、修改、删除。

- 列表用 `QListWidget` + 每行 `QLineEdit` +「保存」「删除」按钮。
- 添加：输入框 +「记下来」；空内容不提交。
- 修改：`POST /api/memory/{id}`；删除：`DELETE /api/memory/{id}`。
- 回车行为对齐 Web：输入框回车 = 添加；行内编辑回车 = 保存该行。
- 验证：假客户端记录调用顺序；添加/修改/删除后列表刷新；404 显示中文错误。
- 提交：`R3.6 Qt 设置页 Agent 记忆`

### R3.7 模块开关 + 保存一致性

**目标**：侧栏模块勾选可保存。

- 从 `/api/modules` 取 id/name/status；`/api/settings.modules` 取勾选值。
- 两列 `QCheckBox`；`status == "planned"` 后加「（待建）」。
- 保存后写回 `/api/settings` 的 `modules`。
- 已知差异（写进验收记录）：Web 页面保存后会立刻 `learnsys:prefs` 更新侧栏；Qt 保存后，**已打开的 Web 页面要刷新才看到变化**。试点不引入跨进程事件；如必须实时，另开任务。
- 验证：勾选/取消 → payload 正确；重新加载后状态保持。
- 提交：`R3.7 Qt 设置页模块开关`

### R3.8 托盘入口、单实例、打包

**目标**：从托盘能打开，重复点只聚焦同一个窗口，打包后也能用。

- 新增 `learnsys/ask/desktop/qt_pilot.py::QtPilotMixin`：
  ```python
  def open_qt_settings(self):
      # _web_port 为 0 → 提示「本地服务还没起来」
      # 第一次：建 ApiClient + SettingsWindow；之后：show/raise/activateWindow
  ```
- `AskApp` 基类加入 `QtPilotMixin`；`tray.py` 菜单加「设置（Qt 试点）」。
- 窗口非模态；`app.setQuitOnLastWindowClosed(False)` 已存在，关闭窗口不退出程序。
- 每次打开（`show()` 前）都调用 `load()` 重新拉取；避免显示上次的旧值。
- PyInstaller：确认 `learnsys.ask.qt.*` 被收集；懒加载若漏，补进 `学习工作台.spec` 的 `hiddenimports`。
- 验证：
  - 托盘点两次 → 同一个窗口实例（比较 `id()` 或窗口标题/指针）。
  - 关闭窗口再打开 → 状态重新拉取。
  - `打包.cmd` 后，从托盘打开 Qt 设置页并保存一次。
- 提交：`R3.8 Qt 设置页入口与打包`

**停点 2**：打包版可用后再做量化验收。

### R3.9 量化验收 + 今日页决策

- 填完 `docs/施工单/R3-验收记录.md` 的功能清单。
- 记录开发耗时：R3.1–R3.8 每步开始/结束时间，合计与 Web 设置页（292 JS + 190 HTML）对比。
- 测内存/启动：
  - Qt：`SettingsWindow` 构造 → `show()` → 首帧（`QTimer.singleShot(0)`）耗时；进程 RSS。
  - Web：Chrome DevTools MCP 的 Performance 面板，记录设置页从导航到表单填完的耗时与标签页内存。
- 测包体：`du -sh dist/学习工作台`，记录 R3 前后差值。
- 跑全量：后端 unittest、两套前端测试、ruff、体量门禁、分层门禁。
- 检查 PWA/远程/MCP：不改后端，跑既有测试 + `/api/health` + MCP 冒烟。
- **决策**：
  - 六项指标全过 → 写「建议进入今日页试点」。
  - 任一项不过 → 停，保留托盘入口或删除；Web 设置页不动。
- 提交：`R3 验收记录`

## 4. 功能清单（必须逐条通过）

| 分组 | 条目 |
|---|---|
| 文本模型 | 服务地址、密钥（留空不改）、主模型、轻量模型、强模型、自动路由、回答上限、速度档、测试连接 |
| Agent 记忆 | 列表、添加、修改、删除、空状态、回车行为 |
| 成本估算 | 输入单价、输出单价、缓存单价、币种 |
| 视觉模型 | 服务地址、密钥（留空不改）、模型、测试连接 |
| 快捷栏 | 快捷键输入、格式错误提示、重启生效提示 |
| 数据与备份 | 数据目录（只读）、设置文件路径、备份目录、立即备份、最近备份路径 |
| 侧栏模块 | 全部模块勾选、待建标记、保存、重新加载保持 |
| 保存语义 | dirty 提示、保存中禁用、成功后刷新掩码、清空密钥、restart_required |
| 错误处理 | 400 中文 detail、403 令牌提示、网络失败、服务未启动 |
| 窗口 | 非模态、单实例、关闭不退出主程序、重新打开重新拉数据 |

## 5. 测试计划

| 层 | 文件 | 内容 |
|---|---|---|
| 纯函数 | `tests/test_qt_api.py` | 错误文案、payload 组装、空密钥剔除 |
| 窗口 | `tests/test_qt_settings.py` | 填充、collect、保存、dirty、测试/备份、记忆 CRUD、模块开关、错误显示 |
| 入口 | `tests/test_qt_pilot.py`（可选） | 单实例、`_web_port=0` 提示 |
| 集成（手动） | 源码 + 打包版 | 真实后台读写一次设置；保存后看 `设置.json`；确认明文密钥不出现 |
| 回归 | 全量 | 708 后端 + 16 网页 + 25 六级 + ruff + 两项门禁 |

约定：

- 所有 Qt 测试 `QT_QPA_PLATFORM=offscreen`，`QApplication` 单例复用。
- 假客户端只记录调用、返回预置 JSON；不碰真实网络、不写真实 `设置.json`。
- 真实后端测试继续用 `fastapi.testclient`（`tests/test_web_v2.py` 口径），Qt 侧不重复测后端校验。

## 6. 量化验收（六项）

| 指标 | 门槛 | 怎么测 |
|---|---|---|
| 功能对齐 | 第 4 节逐条通过 | 验收记录打勾 |
| 开发耗时 | ≤ Web 版同页 1.5 倍 | R3.1–R3.8 工时合计 vs Web 292+190 行 |
| 内存 / 启动 | 不高于现有工作台 | Qt 首帧耗时 + RSS；DevTools 对比 Web |
| 打包体积 | 增量可接受 | `du -sh` R3 前后差值；PySide6 已在包内，预期增量小 |
| 可测试性 | 有自动化测试 | 不靠人眼的条目全部有 unittest |
| 现有能力 | PWA / 远程 / MCP 不受影响 | 不改后端；跑既有测试 + 手动冒烟 |

补充：

- 启动/内存测量工具优先用标准库 + Windows API；不新增 `psutil` 依赖。
- 包体增量 > 5 MB 时必须在验收记录里写原因。

## 7. 风险与回滚

| 风险 | 处理 |
|---|---|
| Qt 窗口与 Web 同时保存 → 后写覆盖 | 保存后都重新 GET；验收记录写明「两边同时开时以后保存的为准」 |
| 模块开关在已打开 Web 页不即时生效 | 验收记录写明「刷新后生效」；不为此加跨进程事件 |
| 懒加载模块被 PyInstaller 漏掉 | R3.8 用打包版实际点一次；必要时补 `hiddenimports` |
| 密钥泄漏到日志/异常 | 不打印 payload；错误文案只带后端 `detail`；测试断言明文不出现 |
| QNetworkAccessManager 在测试里没事件循环 | 窗口测试用假客户端；真实客户端只做手动集成 |
| 窗口阻塞主线程 | 所有请求异步；按钮期间禁用 + 状态标签 |
| 试点失败 | 删除托盘入口 + `learnsys/ask/qt/`；Web 设置页完全不动 |

回滚粒度：每一步一个提交；删掉 `QtPilotMixin` 的基类和托盘 action 即退回 R2 状态。

## 8. 后续（试点达标后再说）

1. **今日页试点**（`web/js/pages/today.js`）：卡片 / 统计 / 行动卡，验证代表性。
2. 资料 / 错题 / 测验等富内容页**不参加首轮**；问一问（Markdown/KaTeX/SSE）最后考虑或保持 Web。
3. 至少两个页面达标后，再讨论 Qt 侧栏/单窗口壳层；在此之前一页一个独立窗口，避免过早造框架。
4. PWA、手机/远程访问、MCP、HTTP API 全程保留。

## 9. 已拍板（2026-10-24）

- 入口文字：**「设置（Qt 试点）」**。
- 记忆列表：`QListWidget` + 行内 `QLineEdit` +「保存」「删除」按钮。
- R3.3 一次做完核心表单（文本 / 成本 / 视觉 / 热键），不拆成两轮。
- 主题：先功能后视觉；试点窗口用中性 QSS，不追求与 Web 主题完全一致。
- R3 完成后是否进今日页：按第 6 节六项指标决定，不提前承诺。

## 10. 读什么 / 练什么

**读：**

- `web/js/pages/settings.js`（292 行）：字段、save、test、backup、memory 的完整口径。
- `web/pages/settings.html`（190 行）：分组与文案。
- `learnsys/server/routes_settings.py`（309 行）：掩码、留空不改、原子写、校验。
- `learnsys/ask/quickbar/bar.py` 与 `tests/test_quickbar_states.py`：现有 Qt 控件与 offscreen 测试写法。

**练：**

1. 起源码后台，用 curl/Python 调一次 `GET /api/settings`，看懂 `auth_token_set/mask/source`。
2. 用 `QDialog` + `QFormLayout` 复刻「文本模型」一组字段。
3. 写一个 `FakeApiClient`，让窗口在无网络下完成「渲染 → 修改 → 保存」测试。
4. 用 `QNetworkAccessManager` 发一次真实 GET，确认令牌从 `/api/health` 来。
5. 打包后从托盘打开，保存一次，检查 `设置.json` 与掩码回显。
