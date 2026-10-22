"""电脑助手：请求 → AI 出计划 → 预览确认 → 后台执行；提醒与番茄钟。"""
from __future__ import annotations

from PySide6 import QtWidgets

from learnsys import config, product, store
from learnsys.ask import ops


class AssistantOpsMixin:
    # ---- 电脑助手：> 请求 → AI 出计划 → 预览确认 → 执行 ----

    def _computer_request(self, request: str) -> None:
        if not request:
            return
        if self.bar._worker is not None:
            self.bar.show_message("上一句还在写 —— 等它写完再叫电脑助手。")
            return
        plan_question = ops.plan_question(request)
        # 电脑助手不是导师：用独立系统提示、关掉工具，只要 JSON 计划。
        self.bar.ask_with_context(plan_question, f"电脑助手：{request}",
                                  mode="quick", system_override=ops.SYSTEM_PROMPT,
                                  use_tools=False)

    def _execute_ops(self, steps: list[dict]) -> None:
        """后台线程逐步执行计划，结果一条条回流到答案区；全量写日志。"""
        import threading
        app_index = ops.start_menu_apps()
        log_lines = [f"--- {store.now()} ---"]

        def run() -> None:
            for i, step in enumerate(steps, 1):
                try:
                    if step.get("op") == "remind":
                        minutes = max(1, int(step.get("minutes") or 1))
                        msg = str(step.get("message") or "提醒")
                        self.bar.remind_scheduled.emit(minutes, msg)
                        result = f"✓ 已设提醒：{minutes} 分钟后 —— {msg}"
                    else:
                        result = "✓ " + ops.execute(step, app_index)
                except Exception as exc:
                    result = f"✗ 第 {i} 步失败：{exc}"
                log_lines.append(f"{i}. [{store.now()}] {ops.describe(step)} → {result}")
                self.bar.ops_result.emit(result)
            log_lines.append("")
            try:
                with open(config.day_dir() / "操作日志.txt", "a", encoding="utf-8") as f:
                    f.write("\n".join(log_lines) + "\n")
            except OSError:
                pass

        threading.Thread(target=run, name="ops-run", daemon=True).start()

    def _schedule_remind(self, minutes: int, message: str) -> None:
        self.scheduler.after(f"remind-{store.now()}", minutes * 60, message)

    def _scheduler_fired(self, name: str, payload) -> None:
        text = str(payload or "时间到。")
        if name.startswith("pomodoro"):
            text = "专注 25 分钟结束 —— 起来走两步，休息 5 分钟。"
            self.scheduler.after("pomodoro_break", 5 * 60, "休息结束 —— 继续加油！")
        self.tray.showMessage(f"{product.PRODUCT_NAME} · 提醒", text,
                              QtWidgets.QSystemTrayIcon.Information, 12000)
        self.bar.show_message("⏰ " + text)
        self.show_bar()

    def _start_pomodoro(self) -> None:
        self.scheduler.after("pomodoro", 25 * 60)
        self._warn("番茄钟开始了 —— 25 分钟后提醒你休息（这段时间适合开个录制）。")
