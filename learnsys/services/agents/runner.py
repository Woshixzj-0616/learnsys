"""任务执行器：起子进程、流式解析、超时/取消、落库与保存结果。

只读边界由 `base.build_argv` 的参数保证；这里不拼接 shell，也不接受模型生成的命令。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time

from learnsys import store
from .base import AgentSpec, build_argv, parse_line

MAX_OUTPUT_CHARS = 5_000_000
MAX_EVENTS = 2000
MAX_STDERR = 20_000

_RUNNING: dict[int, subprocess.Popen] = {}
_CANCEL: dict[int, threading.Event] = {}
_LOCK = threading.Lock()


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


def start_task(task_id: int, spec: AgentSpec, prompt: str, workspace: pathlib.Path,
               timeout_s: int, data_root: pathlib.Path,
               db_path: pathlib.Path | None = None) -> threading.Thread:
    cancel = threading.Event()
    with _LOCK:
        _CANCEL[int(task_id)] = cancel
    thread = threading.Thread(
        target=_run, daemon=True,
        args=(int(task_id), spec, str(prompt), pathlib.Path(workspace),
              int(timeout_s), pathlib.Path(data_root),
              pathlib.Path(db_path) if db_path else None, cancel))
    thread.start()
    return thread


def cancel_task(task_id: int) -> bool:
    with _LOCK:
        event = _CANCEL.get(int(task_id))
        proc = _RUNNING.get(int(task_id))
    if event is not None:
        event.set()
    if proc is not None:
        _kill(proc)
        return True
    return event is not None


def _save_output(data_root: pathlib.Path, task_id: int, spec: AgentSpec,
                 prompt: str, workspace: pathlib.Path, status: str,
                 duration_ms: int, exit_code: int | None, cost: float,
                 answer: str, error: str) -> str:
    folder = data_root / "学习档案" / "agents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id:04d}-{spec.id}.md"
    status_text = {"done": "完成", "failed": "失败", "cancelled": "已取消"}.get(
        status, status)
    lines = [
        f"# Agent 任务 #{task_id} · {spec.name}",
        "",
        f"- 工作目录：{workspace}",
        f"- 状态：{status_text}",
        f"- 耗时：{duration_ms / 1000:.1f} 秒",
        f"- 退出码：{exit_code if exit_code is not None else '—'}",
        f"- CLI 自报费用：{cost:.6f} USD",
        "",
        "## 任务",
        "",
        prompt,
        "",
        "## 结果",
        "",
        answer or "（没有文本输出）",
    ]
    if error:
        lines += ["", "## 错误", "", error]
    body = "\n".join(lines) + "\n"
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(body, encoding="utf-8")
    temp.replace(path)
    try:
        return str(path.relative_to(data_root))
    except ValueError:
        return str(path)


def _run(task_id: int, spec: AgentSpec, prompt: str, workspace: pathlib.Path,
         timeout_s: int, data_root: pathlib.Path, db_path: pathlib.Path | None,
         cancel: threading.Event) -> None:
    conn = store.connect(db_path)
    started = time.monotonic()
    seq = 0
    answer_parts: list[str] = []
    stderr_parts: list[str] = []
    usage: dict = {}
    cost = 0.0
    exit_code: int | None = None
    timed_out = False
    proc: subprocess.Popen | None = None
    error = ""
    status = "failed"

    def emit(kind: str, text: str) -> None:
        nonlocal seq
        if seq >= MAX_EVENTS:
            return
        seq += 1
        store.add_agent_task_event(conn, task_id, seq, kind, text)

    try:
        store.update_agent_task(conn, task_id, status="running", started_at=store.now())
        emit("status", f"启动 {spec.name}（只读）")
        argv = build_argv(spec, prompt, str(workspace))
        proc = subprocess.Popen(
            argv, cwd=str(workspace), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        with _LOCK:
            _RUNNING[task_id] = proc

        def _drain_stderr() -> None:
            total = 0
            for line in proc.stderr or []:
                if total >= MAX_STDERR:
                    break
                stderr_parts.append(line)
                total += len(line)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        def _on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            _kill(proc)

        timer = threading.Timer(max(1, timeout_s), _on_timeout)
        timer.start()
        total_chars = 0
        try:
            for line in proc.stdout or []:
                total_chars += len(line)
                for event in parse_line(spec.kind, line):
                    if event.kind == "text":
                        if event.text:
                            answer_parts.append(event.text)
                            emit("text", event.text)
                    elif event.kind == "tool":
                        emit("tool", event.text)
                    elif event.kind == "status":
                        emit("status", event.text)
                    elif event.kind == "error":
                        emit("error", event.text)
                    elif event.kind == "result":
                        if event.text and not answer_parts:
                            answer_parts.append(event.text)
                            emit("text", event.text)
                        if event.usage:
                            usage = event.usage
                        if event.cost_usd:
                            cost = float(event.cost_usd)
                if total_chars >= MAX_OUTPUT_CHARS or cancel.is_set():
                    _kill(proc)
                    break
        finally:
            timer.cancel()
        try:
            exit_code = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _kill(proc)
            exit_code = proc.wait(timeout=10)
        stderr_thread.join(timeout=2)
        stderr_text = "".join(stderr_parts).strip()
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

        if cancel.is_set():
            status = "cancelled"
            error = "用户停止了任务。"
        elif timed_out:
            status = "failed"
            error = f"超过 {timeout_s} 秒，已停止。"
        elif exit_code != 0:
            status = "failed"
            error = (stderr_text or f"进程退出码 {exit_code}")[:500]
        else:
            status = "done"
            # Claude 的 unrecognized_model 只是警告：成功时不进错误区。
            error = ""
    except Exception as exc:           # 后台异常不能把任务卡在 running
        status = "failed"
        error = f"任务执行失败：{exc}"
        try:
            if proc is not None:
                _kill(proc)
        except Exception:
            pass
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        answer = "\n".join(part for part in answer_parts if part).strip()
        try:
            output_path = _save_output(
                data_root, task_id, spec, prompt, workspace, status,
                duration_ms, exit_code, cost, answer, error)
        except OSError as exc:
            output_path = ""
            error = (error + f"；结果文件没写出来：{exc}").strip("；")
        try:
            store.update_agent_task(
                conn, task_id, status=status, exit_code=exit_code,
                ended_at=store.now(), duration_ms=duration_ms,
                output_path=output_path, error=error,
                cost_usd=cost,
                usage_json=json.dumps(usage, ensure_ascii=False))
            emit("status", {"done": "任务完成", "failed": "任务失败",
                            "cancelled": "任务已取消"}.get(status, status))
        except Exception:
            pass
        with _LOCK:
            _RUNNING.pop(task_id, None)
            _CANCEL.pop(task_id, None)
        conn.close()
