"""显式触发的深度分析：调用用户自己配置的 Claude / 本地 CLI。

边界（与方向决策一致）：
- 只有用户点「深度分析」才跑，绝不自动触发；
- 命令来自设置里的 `agent.deep.command + args`，**不经过 shell**，不是模型生成的；
- 超时、输出上限、中文错误；
- 每次调用写一条 `agent_runs` 审计（不记密钥、不记完整隐私正文）。

设置形状（`D:/学习系统/设置.json`）：
    "agent": {"deep": {"enabled": true, "command": "claude",
                       "args": ["-p"], "timeout": 180,
                       "api_base": "", "api_key": "", "model": ""}}
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import time
import uuid

from learnsys import config as app_config
from learnsys import diagnostics, store
from learnsys.llm import provider_anthropic
from learnsys.llm.config import load_config

MAX_INPUT = 20000
MAX_OUTPUT = 64000
TRUTHY = {"1", "true", "yes", "on", "是", "开"}


def _settings() -> dict:
    agent = app_config.USER.get("agent") if isinstance(app_config.USER, dict) else None
    deep = agent.get("deep") if isinstance(agent, dict) else None
    return deep if isinstance(deep, dict) else {}


def available() -> bool:
    settings = _settings()
    if str(settings.get("enabled") or "").strip().lower() not in TRUTHY:
        return False
    return bool(str(settings.get("command") or "").strip()
                or str(settings.get("api_key") or "").strip())


def describe() -> dict:
    """给界面看的配置（永远不返回密钥）。"""
    settings = _settings()
    return {
        "available": available(),
        "provider": ("command" if str(settings.get("command") or "").strip()
                     else ("api" if str(settings.get("api_key") or "").strip() else "")),
        "model": str(settings.get("model") or ""),
        "timeout": _timeout(settings),
    }


def _timeout(settings: dict) -> int:
    try:
        value = int(settings.get("timeout") or 180)
    except (TypeError, ValueError):
        value = 180
    return max(10, min(value, 900))


def _input(prompt: str, context: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        raise ValueError("深度分析的问题不能为空")
    extra = str(context or "").strip()
    if extra:
        text = f"【上下文】\n{extra[:8000]}\n\n【问题】\n{text}"
    return text[:MAX_INPUT]


def _run_command(text: str, settings: dict) -> str:
    command = str(settings.get("command") or "").strip()
    args = settings.get("args")
    argv = [command] + [str(item) for item in (args if isinstance(args, list) else [])]
    try:
        completed = subprocess.run(          # noqa: S603 —— 命令由用户自己在设置里写死
            argv, input=text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_timeout(settings),
            # Windows 子进程默认按 GBK 输出；统一要求 UTF-8，否则中文会乱码。
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            shell=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"深度分析超过 {_timeout(settings)} 秒，已停止。") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"找不到命令：{command} —— 检查设置里的 agent.deep.command") from exc
    except OSError as exc:
        raise RuntimeError(f"命令没跑起来：{exc}") from exc
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = (completed.stderr or output or "").strip()[:300]
        raise RuntimeError(f"深度分析进程返回 {completed.returncode}：{detail}")
    if not output:
        raise RuntimeError("深度分析没有输出内容。")
    return output[:MAX_OUTPUT]


def _run_api(text: str, settings: dict) -> str:
    base = str(settings.get("api_base") or "https://api.anthropic.com").strip().rstrip("/")
    key = str(settings.get("api_key") or "").strip()
    model = str(settings.get("model") or "").strip()
    if not model:
        raise RuntimeError("深度分析的 API 模式还没填 model。")
    cfg = dataclasses.replace(
        load_config(), base_url=base, auth_token=key, model=model,
        thinking=True, max_tokens=8000)
    messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    parts: list[str] = []
    result = None
    for event in provider_anthropic.stream_messages(
            cfg, "你是深度学习分析助手，用中文回答，给出推理过程和依据。",
            messages, None):
        if event.kind == "text":
            parts.append(event.text)
        elif event.kind == "done":
            result = event.result
    answer = (result.text if result is not None and result.text
              else "".join(parts)).strip()
    if not answer:
        raise RuntimeError("深度分析没有返回内容。")
    return answer[:MAX_OUTPUT]


def run(prompt: str, context: str = "") -> dict:
    """显式跑一次深度分析；返回 {text, provider, model, ms}。失败抛中文异常。"""
    if not available():
        raise RuntimeError(
            "深度分析还没启用：到设置里填 agent.deep（enabled=true，"
            "再配 command/args 或 api_key/model）。")
    settings = _settings()
    text = _input(prompt, context)
    started = time.monotonic()
    run_id = uuid.uuid4().hex[:12]
    provider = "command" if str(settings.get("command") or "").strip() else "api"
    model = str(settings.get("model") or settings.get("command") or "")
    error = ""
    answer = ""
    elapsed = 0
    try:
        answer = (_run_command(text, settings) if provider == "command"
                  else _run_api(text, settings))
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        elapsed = int((time.monotonic() - started) * 1000)
        _audit(run_id, prompt=prompt, model=model, provider=provider,
               ms=elapsed, error=error)
    return {"text": answer, "provider": provider, "model": model,
            "ms": elapsed, "run_id": run_id}


def _audit(run_id: str, *, prompt: str, model: str, provider: str,
           ms: int, error: str) -> None:
    """审计失败不能盖掉主结果 —— 用户要的是答案，不是一条流水。"""
    try:
        conn = store.connect()
        try:
            store.add_agent_run(
                conn, run_id=run_id, question=str(prompt or "")[:200], model=model,
                mode="deep", total_ms=ms,
                stop_reason="error" if error else "end_turn",
                error=error[:500], model_calls=1, error_count=1 if error else 0,
                trace=[{"kind": "deep", "provider": provider}])
        finally:
            conn.close()
    except Exception as exc:
        diagnostics.log_swallow("写深度分析审计流水", exc)
