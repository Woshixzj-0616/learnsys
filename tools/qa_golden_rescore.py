"""按当前 golden set 重算一次在线试点结果；不调模型、不改答案。

用法：
    python tools/qa_golden_rescore.py eval/qa/live-pilot-20261124-105107.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.qa_golden_live import render, score_case

GOLDEN = ROOT / "docs" / "golden" / "qa-golden-50.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按当前题库重算在线试点")
    parser.add_argument("pilot", type=pathlib.Path)
    args = parser.parse_args(argv)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in golden.get("cases") or []}
    pilot = json.loads(args.pilot.read_text(encoding="utf-8"))
    results = pilot.get("results") or []
    for result in results:
        case = cases.get(result.get("id"))
        if case is None or (result.get("score") or {}).get("status") == "跳过":
            continue
        result["score"] = score_case(case, result.get("turns") or [])
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    cfg = types.SimpleNamespace(
        model=pilot.get("model") or "unknown", fast_model="",
        speed="balanced", auto_route="shadow",
        daily_call_limit=int(pilot.get("call_limit") or 0))
    out_dir = ROOT / "eval" / "qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"live-pilot-{stamp}-rescored.json"
    out_json.write_text(json.dumps(
        {"generated_at": generated, "source": str(args.pilot),
         "model": cfg.model, "results": results},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md = ROOT / "docs" / "施工单" / f"P35-在线试点-{stamp}-rescored.md"
    out_md.write_text(render(results, generated, cfg), encoding="utf-8")
    print(f"已写 {out_json}")
    print(f"已写 {out_md}")
    for item in results:
        score = item["score"]
        print(f"{item['id']}: {score['status']} · 首次 {score['first_pass_turn']} · "
              f"工具 {score['tools']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
