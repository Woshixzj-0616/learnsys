"""写作/翻译批改真实模型评测：JSON 合法率、档位稳定性、quote 伪造率、成本。

用法（会调用真实模型、产生费用）：
    .venv/Scripts/python.exe -X utf8 tools/train_eval.py
    ... --limit 3 --samples 1          # 便宜的小样本冒烟
    ... --kind writing --limit 5

样本取内容包自带的范文/参考译文（不是第三方真题答案），每篇跑 N 次（默认 3）。
结果写到 `eval/train/`，临时数据根跑完即删，不碰生产库。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import statistics
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DATA = pathlib.Path(os.environ.get("LEARNSYS_DATA_ROOT") or "D:/学习系统")
OUT_DIR = ROOT / "eval" / "train"


def _temp_root() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="learnsys-train-eval-"))
    settings = SOURCE_DATA / "设置.json"
    if settings.exists():
        shutil.copy2(settings, root / "设置.json")
    return root


def _samples(kind: str, limit: int) -> list[dict]:
    from learnsys.train import content
    rows: list[dict] = []
    if kind in ("", "writing"):
        for item in content.writing_items()[:limit]:
            rows.append({"id": item["id"], "kind": "writing",
                         "prompt_id": item["id"],
                         "text": item["model_essay"]["text"]})
    if kind in ("", "translation"):
        for item in content.translation_items()[:limit]:
            rows.append({"id": item["id"], "kind": "translation",
                         "prompt_id": item["id"], "text": item["reference"]})
    return rows


def _report_md(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# 写作/翻译批改评测",
        "",
        f"- 时间：{report['started_at']}",
        f"- 模型：{report['model']}",
        f"- 样本：{summary['samples']} 篇 × {summary['runs']} 次",
        f"- JSON 合法率：{summary['json_valid_rate']:.0%}",
        f"- 档位稳定（差 ≤1）：{summary['stable_rate']:.0%}",
        f"- 平均档位：{summary['band_mean']}",
        f"- quote 伪造/未命中率：{summary['quote_drop_rate']:.1%}"
        f"（丢弃 {summary['quotes_dropped']} / 共 {summary['quotes_total']}）",
        f"- 总耗时：{summary['ms_total'] / 1000:.1f} 秒",
        f"- token：输入 {summary['tokens_in']} / 输出 {summary['tokens_out']}",
        f"- 估算成本：{summary['cost']} {report.get('currency', '')}",
        "",
        "| 样本 | 类型 | 档位 | 三次档位 | 差 | quote 丢弃 | 耗时 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["samples"]:
        if row.get("error"):
            lines.append(f"| {row['id']} | {row['kind']} | 失败 | - | - | - | "
                         f"{row['error'][:40]} |")
            continue
        bands = ",".join(str(x) for x in row["bands"])
        lines.append(f"| {row['id']} | {row['kind']} | {row['band']} | {bands} | "
                     f"{row['spread']} | {row['quotes_dropped']} | "
                     f"{row['ms'] / 1000:.1f}s |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="训练批改真实模型评测")
    parser.add_argument("--limit", type=int, default=10, help="每类取几篇（默认 10）")
    parser.add_argument("--samples", type=int, default=3, help="每篇跑几次（默认 3）")
    parser.add_argument("--kind", choices=["writing", "translation"], default="",
                        help="只测一类")
    args = parser.parse_args()

    temp_root = _temp_root()
    os.environ["LEARNSYS_DATA_ROOT"] = str(temp_root)
    sys.path.insert(0, str(ROOT))
    try:
        from learnsys.agent import cost
        from learnsys.llm.config import load_config
        from learnsys.services import train_review

        cfg = load_config()
        if not cfg.ready:
            print("失败：没有可用的模型配置（设置.json 缺 key 或 base_url）")
            return 2
        rows = _samples(args.kind, max(1, args.limit))
        print(f"训练批改评测：{len(rows)} 篇 × {args.samples} 次，模型 {cfg.model}")
        print("会调用真实模型并产生费用。")
        samples: list[dict] = []
        for item in rows:
            payload = {"kind": item["kind"], "prompt_id": item["prompt_id"],
                       "text": item["text"], "flags": {}}
            row = {"id": item["id"], "kind": item["kind"]}
            try:
                data = train_review.review_sync(payload, samples=args.samples)
                review = data["review"]
                stability = review.get("stability") or {}
                bands = stability.get("bands") or [review.get("band")]
                dropped = int(review.get("errors_dropped") or 0)
                accepted = len(review.get("errors") or [])
                amount, currency, _ = cost.estimate(
                    data.get("usage"), cfg, data.get("model") or cfg.model)
                row.update({
                    "band": review.get("band"),
                    "bands": bands,
                    "spread": stability.get("spread", 0),
                    "stable": bool(stability.get("stable", True)),
                    "quotes_dropped": dropped,
                    "quotes_accepted": accepted,
                    "ms": data["ms"],
                    "tokens_in": int((data.get("usage") or {}).get("input_tokens") or 0),
                    "tokens_out": int((data.get("usage") or {}).get("output_tokens") or 0),
                    "cost": amount, "currency": currency,
                })
                print(f"  {item['id']}：档位 {review.get('band')} "
                      f"（{','.join(str(x) for x in bands)}），"
                      f"quote 丢弃 {dropped}，{data['ms'] / 1000:.1f}s")
            except Exception as exc:
                row["error"] = str(exc)[:300]
                print(f"  {item['id']}：失败 —— {row['error'][:80]}")
            samples.append(row)

        ok = [row for row in samples if not row.get("error")]
        attempted = args.samples * len(samples)
        returned = sum(len(row.get("bands") or []) for row in ok)
        total_quotes = sum(row.get("quotes_dropped", 0) + row.get("quotes_accepted", 0)
                           for row in ok)
        dropped = sum(row.get("quotes_dropped", 0) for row in ok)
        bands = [row["band"] for row in ok if row.get("band") is not None]
        summary = {
            "samples": len(samples),
            "runs": args.samples,
            "ok": len(ok),
            "json_valid_rate": (returned / attempted) if attempted else 0.0,
            "stable_rate": (sum(1 for row in ok if row.get("stable")) / len(ok)
                            if ok else 0.0),
            "band_mean": round(statistics.mean(bands), 2) if bands else 0,
            "quotes_total": total_quotes,
            "quotes_dropped": dropped,
            "quote_drop_rate": (dropped / total_quotes) if total_quotes else 0.0,
            "ms_total": sum(row.get("ms", 0) for row in ok),
            "tokens_in": sum(row.get("tokens_in", 0) for row in ok),
            "tokens_out": sum(row.get("tokens_out", 0) for row in ok),
            "cost": round(sum(row.get("cost", 0) for row in ok), 6),
        }
        report = {
            "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "model": cfg.model,
            "currency": cfg.currency,
            "summary": summary,
            "samples": samples,
        }
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        json_path = OUT_DIR / f"report-{stamp}.json"
        md_path = OUT_DIR / f"report-{stamp}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        md_path.write_text(_report_md(report), encoding="utf-8")
        print("")
        print(f"JSON 合法率：{summary['json_valid_rate']:.0%}")
        print(f"档位稳定率：{summary['stable_rate']:.0%}，平均档位 {summary['band_mean']}")
        print(f"quote 丢弃：{dropped} / {total_quotes}")
        print(f"估算成本：{summary['cost']} {cfg.currency}")
        print(f"报告：{json_path}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
