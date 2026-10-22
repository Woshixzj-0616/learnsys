# 给协作者 / AI 的说明

> 项目约定；和 `docs/施工单/00-阶段总览.md` 一起看。

## 环境

- Python 用项目 venv：`.venv/Scripts/python.exe`（系统 Python 缺 PySide6）。
- 前端无构建链：Web 工作台是原生 ES modules；六级工作台是单文件 HTML。
- 数据目录：`D:\学习系统`（`LEARNSYS_DATA_ROOT` 可覆盖）。

## 跑测试

```bash
cd "D:/Desktop/learnsys"
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"
```

当前基线：492 个测试全过。

## 打包与发布

```bash
# exe
打包.cmd

# 发布 zip + SHA256
.venv/Scripts/python.exe tools/release.py --version <版本>
.venv/Scripts/python.exe tools/release.py --version <版本> --check-only
```

## 六级精听工作台

- 源码：`D:\cet6_tool\workbench_src\`（12 个 JS + 3 个 CSS + `shell.html`）
- 构建：`python D:\cet6_tool\build_workbench.py --check`
- 部署：`python D:\cet6_tool\split_listening.py --refresh-index --workbench`
- 产物：`D:\Desktop\六级精听\工作台\精听工作台.html`（不要手改）
- 试卷：`D:\Desktop\六级精听\试卷\`（不进 Git）

## 规矩

- 一个功能一个落点；能一份就不做两份。
- 改 schema 只做加法：`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN` / `CREATE INDEX IF NOT EXISTS`。
- 写接口必须 `require_token`；错误信息中文。
- 先写会失败的测试，再实现；跑满再汇报。
- 不自动 push、不自动发版；等负责人发话。
- 文档：方向看 `docs/学习工作台-终版方案-20261021.md`，施工看 `docs/施工单/`。
