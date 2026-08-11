"""
【整段转写（faster-whisper / whisper / openai-api，与 chunked 同级）】
本文件复制自 src/processors/transcriber.py（初版实现），纳入 video2visiondoc 框架
作为同级可切换模块。原始文件保留于 src/ 未作修改。
"""
"""
语音转文字模块
支持: Whisper (OpenAI), faster-whisper, 以及B站已有字幕的直接使用
"""
import os
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Union
import warnings


class AudioTranscriber:
    """音频转录器"""

    def __init__(self, config: Dict):
        self.config = config.get("transcription", {})
        self.engine = self.config.get("engine", "faster-whisper")
        self.model_name = self.config.get("model", "large-v3")
        self.language = self.config.get("language", "auto")
        self.device = self.config.get("device", "cuda")
        self.timestamps = self.config.get("timestamps", True)
        self.word_timestamps = self.config.get("word_timestamps", False)
        self.output_format = self.config.get("output_format", "json")
        self.beam_size = self.config.get("beam_size", 5)
        self.best_of = self.config.get("best_of", 5)
        self.temperature = self.config.get("temperature", 0.0)
        self._model = None

    def _load_model(self):
        """懒加载模型"""
        if self._model is not None:
            return self._model

        if self.engine == "faster-whisper":
            try:
                from faster_whisper import WhisperModel
                compute_type = "float16" if self.device == "cuda" else "int8"
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=compute_type,
                )
                print(f"[转录] faster-whisper 模型 {self.model_name} 加载完成")
            except ImportError:
                raise ImportError("请安装 faster-whisper: pip install faster-whisper")

        elif self.engine == "whisper":
            try:
                import whisper
                self._model = whisper.load_model(self.model_name)
                print(f"[转录] OpenAI Whisper 模型 {self.model_name} 加载完成")
            except ImportError:
                raise ImportError("请安装 openai-whisper: pip install openai-whisper")

        elif self.engine == "openai-api":
            try:
                from openai import OpenAI
                api_key = os.environ.get("OPENAI_API_KEY", "")
                if not api_key:
                    raise ValueError("使用 openai-api 引擎需要设置 OPENAI_API_KEY 环境变量")
                self._model = OpenAI(api_key=api_key)
                print("[转录] OpenAI API 客户端初始化完成")
            except ImportError:
                raise ImportError("请安装 openai: pip install openai")
        else:
            raise ValueError(f"不支持的转录引擎: {self.engine}")

        return self._model

    def transcribe(self, audio_path: str, output_dir: str) -> Dict:
        """
        转录音频文件
        返回: {
            "segments": [
                {"start": float, "end": float, "text": str, "words": [...]},
                ...
            ],
            "text": str,  # 完整文本
            "language": str,
            "output_file": str,
        }
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        base_name = Path(audio_path).stem
        output_file = output_path / f"{base_name}_transcript.{self.output_format}"

        if self.engine in ["faster-whisper", "whisper"]:
            result = self._transcribe_local(audio_path)
        elif self.engine == "openai-api":
            result = self._transcribe_api(audio_path)
        else:
            raise ValueError(f"不支持的引擎: {self.engine}")

        # 保存结果
        if self.output_format == "json":
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        elif self.output_format == "srt":
            self._save_srt(result["segments"], output_file)
        elif self.output_format == "vtt":
            self._save_vtt(result["segments"], output_file)
        elif self.output_format == "txt":
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result["text"])

        result["output_file"] = str(output_file)
        print(f"[转录] 结果已保存: {output_file}")
        return result

    def _transcribe_local(self, audio_path: str) -> Dict:
        """本地模型转录"""
        model = self._load_model()

        if self.engine == "faster-whisper":
            segments_iter, info = model.transcribe(
                audio_path,
                language=None if self.language == "auto" else self.language,
                beam_size=self.beam_size,
                best_of=self.best_of,
                temperature=self.temperature,
                word_timestamps=self.word_timestamps,
            )

            segments = []
            full_text = []
            for segment in segments_iter:
                seg = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                }
                if self.word_timestamps and segment.words:
                    seg["words"] = [
                        {"start": w.start, "end": w.end, "word": w.word}
                        for w in segment.words
                    ]
                segments.append(seg)
                full_text.append(segment.text.strip())

            return {
                "segments": segments,
                "text": " ".join(full_text),
                "language": info.language,
            }

        elif self.engine == "whisper":
            result = model.transcribe(
                audio_path,
                language=None if self.language == "auto" else self.language,
                temperature=self.temperature,
                word_timestamps=self.word_timestamps,
            )

            segments = []
            for seg in result.get("segments", []):
                segment = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"].strip(),
                }
                if self.word_timestamps and "words" in seg:
                    segment["words"] = seg["words"]
                segments.append(segment)

            return {
                "segments": segments,
                "text": result.get("text", ""),
                "language": result.get("language", ""),
            }

    def _transcribe_api(self, audio_path: str) -> Dict:
        """OpenAI API 转录"""
        client = self._load_model()

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json" if self.timestamps else "json",
                timestamp_granularities=["segment"] if self.timestamps else None,
            )

        if self.timestamps:
            segments = []
            for seg in transcript.segments:
                segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                })
            return {
                "segments": segments,
                "text": transcript.text,
                "language": transcript.language if hasattr(transcript, "language") else "",
            }
        else:
            return {
                "segments": [],
                "text": transcript.text,
                "language": "",
            }

    def use_bili_subtitle(self, subtitle_data: List[Dict]) -> Dict:
        """
        直接使用B站已有字幕
        subtitle_data: BiliVideoExtractor.get_subtitle() 的返回值
        """
        if not subtitle_data:
            return None

        # 优先选择英文或中文
        preferred = ["en-US", "en", "zh-CN", "zh", "ai-zh", "ai-en"]
        selected = None
        for pref in preferred:
            for sub in subtitle_data:
                if sub.get("lan", "").startswith(pref):
                    selected = sub
                    break
            if selected:
                break

        if not selected:
            selected = subtitle_data[0]  # 默认第一个

        content = selected.get("content", {})
        body = content.get("body", [])

        segments = []
        full_text = []
        for item in body:
            seg = {
                "start": item.get("from", 0),
                "end": item.get("to", 0),
                "text": item.get("content", "").strip(),
            }
            segments.append(seg)
            full_text.append(seg["text"])

        return {
            "segments": segments,
            "text": " ".join(full_text),
            "language": selected.get("lan", ""),
            "source": "bilibili_subtitle",
        }

    def _save_srt(self, segments: List[Dict], path: Path):
        """保存为SRT格式"""
        def fmt_time(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

        with open(path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")

    def _save_vtt(self, segments: List[Dict], path: Path):
        """保存为VTT格式"""
        def fmt_time(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}"

        with open(path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for seg in segments:
                f.write(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")
