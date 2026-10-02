"""本地转写：faster-whisper 包一层（懒加载，别拖慢开窗）。"""
from __future__ import annotations

import numpy as np


class Transcriber:
    def __init__(self, model_dir: str, device: str = "cpu", compute_type: str = "int8",
                 language: str = "zh", hotwords: str = "", beam_size: int = 5, vad: bool = True):
        self.model_dir = model_dir
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.hotwords = hotwords
        self.beam_size = beam_size
        self.vad = vad
        self.model = None
        self.load_error = ""

    def load(self) -> bool:
        """加载模型（第一次调用才真正 import + 读盘）。"""
        if self.model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.model_dir, device=self.device,
                                      compute_type=self.compute_type)
            return True
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            return False

    def transcribe(self, samples: np.ndarray) -> list[tuple[float, float, str]]:
        """一段 16kHz 单声道音频 → [(起点秒, 终点秒, 文本)]；失败返回空表。"""
        if not self.load():
            return []
        for use_vad in ([True, False] if self.vad else [False]):
            try:
                segments, _info = self.model.transcribe(
                    samples,
                    language=self.language,
                    beam_size=self.beam_size,
                    initial_prompt=self.hotwords or None,
                    vad_filter=use_vad,
                    condition_on_previous_text=False,
                )
                out = []
                for seg in segments:
                    text = (seg.text or "").strip()
                    if text:
                        out.append((float(seg.start), float(seg.end), text))
                if use_vad is False and self.vad:
                    self.vad = False      # VAD 这条路不通，以后别再试
                return out
            except Exception as exc:
                self.load_error = f"{type(exc).__name__}: {exc}"
                continue
        return []