# 六级精听工作台源码（版本快照）

> 这不是运行时代码，也不会被打进发布包；它只是给六级工作台源码一个**版本兜底**。

## 真源在哪

- 日常修改与构建：`D:\cet6_tool`
  - 工作台源码：`workbench_src/`（18 个 JS + 3 个样式 + `shell.html`）
  - 校对补丁：`校对/*.json`（每份试卷一份 + `结构修复.json`）
  - 构建：`python build_workbench.py` → `D:\Desktop\六级精听\工作台\精听工作台.html`
- 本目录：上述**文本源码**的单向快照，随仓库提交。

## 为什么有两份

试卷、逐句 MP3、整段音频、抓取缓存体积大且涉及版权，不能进 Git；
但源码如果只留在磁盘上，换机 / 误删就没有任何恢复手段。
所以只把**能重建产物的文本**放进仓库。

## 同步

```bash
python tools/sync_cet6_src.py            # D:\cet6_tool → cet6-src/
python tools/sync_cet6_src.py --check    # 检查仓库是否落后（落后返回 1）
```

`--check` 已接入 `tests/test_cet6_src.py`：D 盘源码存在时，测试会报漂移。
改完六级源码、提交本仓库之前，先跑一次同步。

## 不进来的东西

`试卷/`、`*.mp3`、`*.wav`、`_tmp*`、`_src_*`、`_dump*`、`models/`、`__pycache__`。
构建产物（`精听工作台.html`）也不进来，它由 `build_workbench.py` 生成。

## 注意

校对 / 重切脚本里的默认目录写的是作者本机路径（`D:\Desktop\六级精听\试卷`、
`D:\cet6_tool\校对`），都可用 `--papers` / `--dir` 参数覆盖；换机时按需改参数，不用改脚本。
