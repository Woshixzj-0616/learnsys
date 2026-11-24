# -*- coding: utf-8 -*-
"""问答 golden set 在线试点报告渲染（只拼 Markdown，不调模型）。

从 `qa_golden_live.py` 拆出，守住单文件体量门禁；在线 harness 与重打分共用。
"""
from __future__ import annotations


def render(results: list[dict], generated: str, cfg) -> str:
    lines = [
        "# P35.2 在线试点（问答 golden set）",
        "",
        f"> 生成时间：{generated}",
        f"> 模型：{cfg.model}（fast={cfg.fast_model}，speed={cfg.speed}，auto_route={cfg.auto_route}）",
        f"> 临时库每日上限：{cfg.daily_call_limit} 次",
        "> 多轮用例：有 `conversation_id` 的会先回放第一句受测问题之前的原会话前文，再把 `turns` 作为受测轮次。",
        "",
        "| 用例 | 类别 | 结果 | 轮数 | 首次通过 | 工具 | 引用 | 伪造 | 调用 | 花费 |",
        "|---|---|---|---:|---:|---|---|---|---:|---:|",
    ]
    for item in results:
        score = item["score"]
        citation = "—" if score["citation_ok"] is None else ("是" if score["citation_ok"] else "否")
        fake = []
        if score.get("fake_urls"):
            fake.append(f"链接 {len(score['fake_urls'])} 个")
        if score.get("fake_dates"):
            fake.append(f"日期 {len(score['fake_dates'])} 个")
        name = item["id"] + (f" · 第{item['run']}次" if item.get("run") else "")
        lines.append(
            f"| {name} | {item['category']} | {score['status']} | "
            f"{item['turns_run']} | {score['first_pass_turn'] or '—'} | "
            f"{'、'.join(score['tools']) or '—'} | {citation} | "
            f"{'、'.join(fake) or '0'} | "
            f"{score['model_calls']} | {score['cost']:.4f} |")
    if any(item.get("run") for item in results):
        lines += ["", "## 重复运行汇总（一条用例所有轮次都通过才算通过）", "",
                  "| 用例 | 次数 | 通过 | 未通过 | 负例违规 | 结论 |",
                  "|---|---:|---:|---:|---:|---|"]
        ids = []
        for item in results:
            if item["id"] not in ids:
                ids.append(item["id"])
        for case_id in ids:
            rows = [item for item in results if item["id"] == case_id]
            passed = sum(1 for item in rows if item["score"]["status"] == "通过")
            bad = sum(len(item["score"].get("behavior_violations") or []) for item in rows)
            lines.append(
                f"| {case_id} | {len(rows)} | {passed} | {len(rows) - passed} | "
                f"{bad} | {'全部通过' if passed == len(rows) else '未通过'} |")
    lines += ["", "## 逐条回答（前 400 字）", ""]
    for item in results:
        name = item["id"] + (f" · 第{item['run']}次" if item.get("run") else "")
        lines.append(f"### {name} · {item['score']['status']}")
        if item["score"].get("reason"):
            lines.append(f"- **跳过原因**：{item['score']['reason']}")
        for url in item["score"].get("fake_urls") or []:
            lines.append(f"- **伪造链接**：{url}")
        for date in item["score"].get("fake_dates") or []:
            lines.append(f"- **伪造日期**：{date}")
        for bad in item["score"].get("behavior_violations") or []:
            lines.append(
                f"- **负例违规**：第 {bad['turn']} 轮命中「{bad['pattern']}」"
                f"——{bad['sentence']}")
        for turn in item["turns"]:
            answer = " ".join(str(turn["answer"]).split())[:400]
            lines.append(f"- **问**：{turn['question']}")
            lines.append(f"  **答**：{answer}")
            if turn["tools"]:
                lines.append(f"  **工具**：{'、'.join(turn['tools'])}")
            if turn["errors"]:
                lines.append(f"  **错误**：{'；'.join(turn['errors'])}")
        lines.append("")
    return "\n".join(lines)
