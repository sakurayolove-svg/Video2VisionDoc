"""
transcriber.py —— 语音转写（faster-whisper 分块，防 OOM）

实战经验（4GB 内存 / 2 核 CPU 容器验证）：
    - medium 模型整段转写 35 分钟音频会被 cgroup OOM 杀掉；
    - 即使 small 模型，整段处理（VAD 要在全长音频上建缓冲区）也会 OOM；
    - 解决方案：先用 ffmpeg 把音频切成 5 分钟一块（-c copy 秒切），
      逐块转写、即时落盘，内存占用稳定，small 模型可全程跑完；
    - 每块转写后把段时间戳加上块偏移量，拼成全局时间轴。

依赖：faster-whisper、ffmpeg。
模型下载慢时可设置环境变量：
    HF_ENDPOINT=https://hf-mirror.com  HF_HUB_DISABLE_XET=1
"""

import json
import math
import subprocess
import wave
from pathlib import Path


def _wav_duration(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


class ChunkedTranscriber:
    """分块转写器：低内存环境下的稳妥选择"""

    def __init__(self,
                 model_size: str = "small",
                 device: str = "cpu",
                 compute_type: str = "int8",
                 chunk_seconds: int = 300,
                 beam_size: int = 3,
                 language: str = "en",
                 initial_prompt: str = ""):
        """
        model_size:    tiny/base/small/medium/large-v3（4GB 内存建议 ≤ small）
        chunk_seconds: 分块长度，默认 300s
        initial_prompt: 领域提示词，可显著改善专有名词识别，
                        例如 "Talk on sparse rewards in reinforcement learning,
                        Andrews-Curtis conjecture, knot theory, topology."
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "语音转写需要 faster-whisper：pip install faster-whisper")
        self.model = WhisperModel(model_size, device=device,
                                  compute_type=compute_type, cpu_threads=2)
        self.chunk_seconds = chunk_seconds
        self.beam_size = beam_size
        self.language = language
        self.initial_prompt = initial_prompt

    def _split(self, audio_path: str, chunk_dir: Path) -> list:
        """用 ffmpeg 无损切分音频为固定长度分块"""
        chunk_dir.mkdir(parents=True, exist_ok=True)
        duration = _wav_duration(audio_path)
        n = math.ceil(duration / self.chunk_seconds)
        paths = []
        for i in range(n):
            out = chunk_dir / f"chunk_{i}.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(i * self.chunk_seconds),
                 "-t", str(self.chunk_seconds),
                 "-i", audio_path, "-c", "copy", str(out)],
                check=True, capture_output=True)
            paths.append(out)
        return paths

    def transcribe(self, audio_path: str, workdir: str) -> list:
        """
        分块转写整个音频。
        返回 segments: [{"start": float, "end": float, "text": str}, ...]
        同时写入 workdir/transcript.json（每块完成后增量保存，
        中途崩溃可从 partial 文件恢复进度）。
        """
        workdir = Path(workdir)
        chunks = self._split(audio_path, workdir / "chunks")
        all_segments = []
        partial_path = workdir / "transcript_partial.json"

        for i, chunk_path in enumerate(chunks):
            offset = i * self.chunk_seconds
            segments, _ = self.model.transcribe(
                str(chunk_path),
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,            # 跳过静音，显著提速
                initial_prompt=self.initial_prompt or None,
            )
            for s in segments:
                all_segments.append({
                    "start": round(s.start + offset, 2),
                    "end": round(s.end + offset, 2),
                    "text": s.text.strip(),
                })
            # 每块完成即落盘（崩溃保护 + 进度可见）
            with open(partial_path, "w", encoding="utf-8") as f:
                json.dump(all_segments, f, ensure_ascii=False)
            print(f"  块 {i + 1}/{len(chunks)} 完成，"
                  f"累计 {len(all_segments)} 段")

        out_path = workdir / "transcript.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_segments, f, ensure_ascii=False)
        print(f"  转写完成: {len(all_segments)} 段 → {out_path}")
        return all_segments
