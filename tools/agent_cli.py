"""命令行跑一轮 Agent —— 不启动界面，用来验证模型接入。

用法：
  .venv\\Scripts\\python.exe tools\\agent_cli.py "解释一下循环队列"
  .venv\\Scripts\\python.exe tools\\agent_cli.py --image D:\\学习系统\\...\\shot.png "这张图在讲什么"
  .venv\\Scripts\\python.exe tools\\agent_cli.py --mode guide "二叉树的遍历为什么分前中后序"

密钥读取顺序见 learnsys/agent/config.py；不会打印密钥。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learnsys.agent import AgentRequest, run          # noqa: E402
from learnsys.agent.config import load_config         # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")      # Windows 控制台别把中文打成乱码
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="学习系统 Agent 命令行")
    parser.add_argument("question", help="要问的问题")
    parser.add_argument("--image", default="", help="截图路径（可选）")
    parser.add_argument("--mode", default="explain",
                        choices=["explain", "guide", "quiz", "quick"])
    parser.add_argument("--max-tokens", type=int, default=0, help="覆盖 max_tokens")
    args = parser.parse_args()

    cfg = load_config()
    if args.max_tokens:
        cfg = cfg.__class__(**{**cfg.__dict__, "max_tokens": args.max_tokens})
    print(f"模型：{cfg.model} ｜ 视觉：{'已配置 ' + cfg.vision_model if cfg.vision_ready else '未配置（OCR 兜底）'}")
    print(f"地址：{cfg.base_url}")
    if not cfg.ready:
        print("✗ 还没配置模型：在 D:\\学习系统\\设置.json 里填 agent.base_url / auth_token / model，")
        print("  或者让 ~/.claude/settings.json 里有 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN。")
        return 2
    print("-" * 60)

    started = time.monotonic()
    thinking_shown = False
    final = ""
    request = AgentRequest(
        message=args.question,
        image_path=args.image or None,
        mode=args.mode,
    )
    for event in run(request, cfg=cfg):
        if event.kind == "thinking":
            if not thinking_shown:
                print("（推理中…）", end="", flush=True)
                thinking_shown = True
        elif event.kind == "vision":
            if event.text:
                print(f"\n[看图] {event.text}", flush=True)
            elif event.data:
                print(f"[看图] 视觉模型={'用了' if event.data.get('used_vision') else '没用'}",
                      flush=True)
        elif event.kind == "text":
            if thinking_shown:
                print("\n", end="", flush=True)
                thinking_shown = False
            print(event.text, end="", flush=True)
        elif event.kind == "tool_start":
            print(f"\n[工具] {event.data.get('name')} {event.data.get('input')}", flush=True)
        elif event.kind == "tool_end":
            print(f"[工具] {event.data.get('preview')}", flush=True)
        elif event.kind == "error":
            print(f"\n✗ {event.text}")
            return 1
        elif event.kind == "done":
            final = str(event.data.get("text") or "")
            usage = event.data.get("usage") or {}
            print(f"\n\n{'=' * 60}")
            print(f"用时 {time.monotonic() - started:.1f} 秒 ｜ 步数 {event.data.get('steps')} "
                  f"｜ 结束 {event.data.get('stop_reason')} ｜ tokens {usage or '—'}")
            if final:
                print(f"正文 {len(final)} 字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
