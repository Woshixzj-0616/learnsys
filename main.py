"""学习记录器 v1 · 主窗口

两路在记：
  · 看：每秒采一次前台窗口（进程名 + 标题）
  · 听：抓系统声音回环，每 25 秒本地转写一段，只把**文本**落库（原始音频不留盘）

屏幕关键帧 + OCR 还没接。你有问题时，AI 按时间 / 关键词查这张库就能结合着回答。
"""
from __future__ import annotations

import datetime as dt
import queue
import threading
import time
import tkinter as tk

import numpy as np

from learnsys import asr, audio, capture, config, store

TITLE = "学习记录器"
FONT = "Microsoft YaHei UI"


def hhmmss(seconds: int) -> str:
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def level_bar(rms: float, width: int = 10) -> str:
    filled = int(min(1.0, rms * 12.0) * width)
    return "▮" * filled + "▯" * (width - filled)


class Recorder:
    """后台采样线程：每秒记一条前台窗口。"""

    def __init__(self, conn, session_id: int, events: queue.Queue):
        self.conn = conn
        self.session_id = session_id
        self.events = events
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="window", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            process, title = capture.sample()
            if title or process:
                store.add_window_event(self.conn, self.session_id, process, title)
                self.events.put((store.now(), process, title))
            self._stop.wait(config.WINDOW_SAMPLE_SECONDS)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.conn = store.connect()
        self.recorder = None
        self.audio = None
        self.session_id = None
        self.started_at = None
        self.chunks = queue.Queue()
        self.ui = queue.Queue()
        self.transcriber = None

        self._build()
        self.root.after(200, self._drain)

    def _build(self) -> None:
        self.root.title(TITLE)
        self.root.geometry("480x580")
        self.root.minsize(440, 500)
        pad = {"padx": 14, "pady": 5}

        self.status = tk.Label(self.root, text="未开始", font=(FONT, 16, "bold"), fg="#888888")
        self.status.pack(**pad, anchor="w")

        self.clock = tk.Label(self.root, text="已记录 00:00:00", font=(FONT, 11))
        self.clock.pack(**pad, anchor="w")

        btns = tk.Frame(self.root)
        btns.pack(**pad, anchor="w")
        self.btn_start = tk.Button(btns, text="开始记录", width=12, font=(FONT, 10), command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(btns, text="结束记录", width=12, font=(FONT, 10), state="disabled", command=self.stop)
        self.btn_stop.pack(side="left", padx=8)

        self.stats = tk.Label(self.root, text="窗口事件 0 条 · 不同窗口 0 个", font=(FONT, 10))
        self.stats.pack(**pad, anchor="w")
        self.tstats = tk.Label(self.root, text="转写 0 条 · 0 字", font=(FONT, 10))
        self.tstats.pack(**pad, anchor="w")
        self.level = tk.Label(self.root, text="声音 ▯▯▯▯▯▯▯▯▯▯", font=(FONT, 10))
        self.level.pack(**pad, anchor="w")

        tk.Label(self.root, text="最近的转写（新→旧）：", font=(FONT, 10)).pack(**pad, anchor="w")
        self.list = tk.Listbox(self.root, height=13, font=(FONT, 9))
        self.list.pack(fill="both", expand=True, padx=14)

        self.hint = tk.Label(self.root, text="", font=(FONT, 8), fg="#777777",
                             wraplength=450, justify="left")
        self.hint.pack(**pad, anchor="w")
        self.hint.config(text=f"数据：{config.db_path()}\n模型：{config.ASR_MODEL_DIR}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- 开始 / 结束 ----

    def start(self) -> None:
        self.session_id = store.start_session(self.conn)
        self.started_at = dt.datetime.now()
        self.list.delete(0, "end")

        self.recorder = Recorder(self.conn, self.session_id, self.ui)
        self.recorder.start()

        self.chunks = queue.Queue()
        self.audio = audio.LoopbackRecorder(self.chunks, chunk_seconds=config.CHUNK_SECONDS)
        self.audio.start()
        threading.Thread(target=self._asr_loop, name="asr", daemon=True,
                         args=(self.session_id, self.chunks)).start()
        threading.Thread(target=self._watch_players, name="watch", daemon=True).start()

        self.status.config(text="● 记录中", fg="#1a7f37")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._tick()

    def stop(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()
            self.recorder = None
        if self.audio is not None:
            self.audio.stop()
            self.audio = None
        if self.session_id is not None:
            store.end_session(self.conn, self.session_id)
        self.status.config(text="已结束（数据已存）", fg="#888888")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    # ---- 转写线程 ----

    def _asr_loop(self, session_id: int, chunks: queue.Queue) -> None:
        tr = asr.Transcriber(
            config.ASR_MODEL_DIR, config.ASR_DEVICE, config.ASR_COMPUTE_TYPE,
            config.ASR_LANGUAGE, config.HOTWORDS, config.ASR_BEAM_SIZE, config.ASR_VAD,
        )
        self.transcriber = tr
        self.ui.put(("info", "正在加载转写模型（十几秒）…"))
        if not tr.load():
            self.ui.put(("error", f"转写模型加载失败：{tr.load_error}"))
            return
        self.ui.put(("info", "转写就绪，开始听"))
        while True:
            item = chunks.get()
            if item is None:
                break
            started, samples = item
            if samples.size < config.MIN_CHUNK_SECONDS * 16000:
                continue
            rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
            if rms < config.SILENCE_RMS:
                self.ui.put(("info", f"{store.stamp(started)[11:]} 静音，跳过"))
                continue
            for s, e, text in tr.transcribe(samples):
                ts_start = store.stamp(started + dt.timedelta(seconds=s))
                ts_end = store.stamp(started + dt.timedelta(seconds=e))
                store.add_transcript(self.conn, session_id, ts_start, ts_end, text)
                self.ui.put(("text", ts_start, text))
        self.ui.put(("info", "转写线程已收工"))

    # ---- 盯「谁还在放声音」----

    def _watch_players(self) -> None:
        """有别的程序在往扬声器送声音（游戏 / 音乐）时提醒：它会一起被转写进去。"""
        warned = set()
        while self.recorder is not None:
            for name, peak in audio.active_players():
                if name not in warned:
                    warned.add(name)
                    self.ui.put(("warn", f"{name} 也在放声音（峰值 {peak}），会混进转写，建议关掉或静音"))
            time.sleep(20)

    # ---- UI 刷新 ----

    def _tick(self) -> None:
        if self.started_at is None or self.session_id is None:
            return
        secs = (dt.datetime.now() - self.started_at).total_seconds()
        self.clock.config(text=f"已记录 {hhmmss(secs)}")
        st = store.session_stats(self.conn, self.session_id)
        self.stats.config(text=f"窗口事件 {st['窗口行数']} 条 · 不同窗口 {st['不同窗口']} 个")
        self.tstats.config(text=f"转写 {st['转写条数']} 条 · {st['转写字数']} 字")
        if self.audio is not None:
            if self.audio.error:
                self.level.config(text="声音 ✗ 没在采", fg="#b00020")
                self.ui.put(("error", self.audio.error))
            else:
                self.level.config(text=f"声音 {level_bar(self.audio.level)}  {self.audio.level:.3f}",
                                  fg="#1a7f37" if self.audio.level > config.SILENCE_RMS else "#888888")
        self.root.after(500, self._tick)

    def _drain(self) -> None:
        try:
            while True:
                msg = self.ui.get_nowait()
                if msg[0] == "text":
                    self.list.insert(0, f"{msg[1][11:]}  {msg[2][:40]}")
                    self.list.itemconfig(0, fg="#111111")
                elif msg[0] == "warn":
                    self.list.insert(0, f"⚠ {msg[1][:60]}")
                    self.list.itemconfig(0, fg="#b26a00")
                elif msg[0] == "error":
                    self.list.insert(0, f"⚠ {msg[1][:60]}")
                    self.list.itemconfig(0, fg="#b00020")
                else:
                    self.list.insert(0, f"· {msg[1][:60]}")
                    self.list.itemconfig(0, fg="#888888")
                if self.list.size() > 400:
                    self.list.delete(400, "end")
        except queue.Empty:
            pass
        self.root.after(200, self._drain)

    def _on_close(self) -> None:
        if self.recorder is not None or self.audio is not None:
            self.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
