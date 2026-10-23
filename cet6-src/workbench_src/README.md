# 精听工作台源码

这里是工作台的**唯一源码**。`D:\cet6_tool\workbench_template.html` 是构建产物，不要手改它；部署到 `D:\Desktop\六级精听\工作台\精听工作台.html` 的文件同样由构建脚本生成。

## 为什么还要构建成单文件

工作台通过 `file://` 直接双击打开。ES module 在 `file://` 下会被 CORS 拦截，多文件部署也容易搬丢。因此源码按层拆分，构建时把 CSS/JS 全部内联回一份自包含 HTML。

## 目录

```
workbench_src\
├─ shell.html                 ← 页面骨架；{{WB_CSS}} / {{WB_JS}} 是构建占位符
├─ styles\
│  ├─ base.css                变量、头部、侧栏、工具栏、按钮、进度
│  ├─ cards.css               句子卡片、mini 播放条、循环、A-B、笔记、断点
│  └─ panels.css              搜索、AI、统计、生词本、题目、划词浮钮
└─ js\
   ├─ 00-core.js               WB 命名空间、DOM 缓存、格式化工具、session 默认值、退休常量
   ├─ 04-mode.js               HTTP/file/只读模式、写入口守卫、只读横幅
   ├─ 05-bridge.js             旧 file:// ↔ 学习后台的迁移桥（退休后只读）
   ├─ 10-storage.js            所有 localStorage 键、状态读写、历史/最近、导出入
   ├─ 20-paper.js              试卷模型、当前段/题型、句范围、学习状态（含 A-B）
   ├─ 25-ranges.js             整段/整篇区间与上下文载荷（纯函数）
   ├─ 30-audio.js              音频状态机：range、循环/连播、A-B、边界定时器
   ├─ 40-render.js             只读状态并渲染 DOM
   ├─ 50-actions.js            用户操作 → paper/audio 调用
   ├─ 55-api.js                HTTP 令牌、请求、SSE
   ├─ 56-dualwrite.js          服务端行映射、整卷快照、结构指纹（纯函数）
   ├─ 58-sync.js               增量同步 + 打开试卷时的整卷审计
   ├─ 60-insights.js           AI 本段/整卷、学习统计
   ├─ 65-ask.js                AI 助手 / 会话
   ├─ 68-translate.js          划词翻译与整段译文
   ├─ 70-vocab.js              生词本、划词、CSV
   ├─ 75-search.js             本卷句子搜索
   ├─ 80-shortcuts.js          键盘快捷键
   ├─ 90-boot.js               WB.boot(ctx)，只定义不执行
   └─ 99-launcher.js           加载索引/data.js，最后调用 WB.boot
```

## 依赖方向

```
core → storage → paper → audio → render → actions → insights / vocab / search
     → shortcuts → boot → launcher
```

- 每个文件是一个 IIFE，只通过 `window.WB` 通信；文件头 `// @requires:` 声明前置文件，构建脚本会校验顺序。
- `WB.state` 是持久化数据，`WB.session` 是运行态，`WB.dom` 是静态 DOM 缓存。
- localStorage 的键定义与状态读写主要在 `10-storage.js`；`05-bridge.js`（迁移标记/合并）和
  `70-vocab.js`（file:// 生词本）也直接碰它。播放器时钟只在 `30-audio.js`；渲染函数只读状态。
- `WB.FLAGS.retired` 是双写退休的硬开关（`00-core.js`）；改 true 后重建工作台，
  file:// 变只读，HTTP 成为唯一写入口。
- 音频向 UI 通知走回调：`WB.audio.onTick / onWindowChange / onLoopStat / onRateChange`，由 `90-boot.js` 绑定。

## 数据键

| 键 | 内容 |
|---|---|
| `listening_splitter_v1_<paper_id 或 title>` | 每份试卷的学习状态：`done/errors/starts/notes/analysis/daily/pos/loopCfg/loopStats/ab` |
| `listening_workbench_vocab_v1` | 生词本 |
| `listening_workbench_history_v1` | 最近听过的试卷 |
| `listening_workbench_last_paper_v1` | 上次打开的试卷 |
| `listening_workbench_rate_v1` | 倍速 |

`ab[itemId][sentenceIndex] = {a, b}`；B 只有在 `b > a + 0.2` 时生效，否则按整句播放并提示。

## 构建与部署

```bat
cd /d D:\cet6_tool
.venv\Scripts\python.exe build_workbench.py
.venv\Scripts\python.exe build_workbench.py --check
```

- `build_workbench.py` 默认输出 `workbench_template.html`，打印构建哈希。
- 部署走原来的 `拖入音频分割.bat` 或 `--refresh-index --workbench`；`install_workbench()` 会按需重新构建，构建失败时不会复制旧产物。
- 产物顶部有 `<!-- WB-BUILD hash=... -->`，`--check` 用它判断是否过期。

## 加一个功能

1. 数据/持久化改动放 `10-storage.js` 或 `20-paper.js`。
2. 播放相关放 `30-audio.js`；只读 DOM 输出放 `40-render.js`；用户操作放 `50-actions.js`。
3. 新文件按数字前缀命名，并在文件头写 `// @requires: 前置文件.js`。
4. 构建 + 浏览器回归；不要把逻辑加回 `workbench_template.html`。
