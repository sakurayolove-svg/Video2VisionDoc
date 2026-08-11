"""
backends.py —— v1 初版模块的复用适配层

本模块不修改 src/ 下的任何 v1 代码，只做两件事：
    1. 把 v1 各模块包装成与 v2 流水线一致的数据接口；
    2. 供 pipeline.py 在配置切换到 v1 后端时调用。

当配置为 v2 默认值时，本模块完全不会被激活
（pipeline 直接调用 v2 实现，代码与实战验证时完全一致）。

v1 模块位置（复用来源）：
    src/extractors/bilibili.py        BiliVideoExtractor   → yt-dlp 下载
    src/processors/transcriber.py     AudioTranscriber     → 整段转写/字幕复用
    src/extractors/frame_extractor.py FrameExtractor       → PPT 布局分析抽帧
    src/processors/translator.py      TextTranslator       → 逐段翻译（3 引擎）
    src/generators/vision_doc.py      VisionDocGenerator   → 模板化文档生成
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ========== 下载：v1 yt-dlp 后端 ==========

def download_via_ytdlp(url: str, workdir: str, config: dict) -> dict:
    """复用 v1 BiliVideoExtractor（yt-dlp 下载），归一化为 v2 返回结构"""
    from src.extractors.bilibili import BiliVideoExtractor
    extractor = BiliVideoExtractor(config)
    result = extractor.download_video(url, workdir)
    info = result["info"]
    return {
        "info": {
            "bvid": result["bvid"],
            "aid": info.get("aid"),
            "cid": result.get("cid"),
            "title": result["title"],
            "duration": result.get("duration", 0),
            "owner": info.get("owner", {}).get("name", ""),
            "desc": info.get("desc", ""),
        },
        "video_path": result["video_path"],
        "audio_path": result["audio_path"],
        "subtitles": result.get("subtitles"),
    }


# ========== 转写：v1 整段模式后端 ==========

def transcribe_standard(audio_path: str, workdir: str, config: dict) -> list:
    """复用 v1 AudioTranscriber（整段转写，多引擎），返回 v2 段列表"""
    from src.processors.transcriber import AudioTranscriber
    transcriber = AudioTranscriber(config)
    result = transcriber.transcribe(audio_path, workdir)
    return [{"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])]


def transcribe_via_bili_subtitle(subtitles: list, config: dict) -> list:
    """复用 v1 的 B 站字幕直接转段功能"""
    from src.processors.transcriber import AudioTranscriber
    transcriber = AudioTranscriber(config)
    result = transcriber.use_bili_subtitle(subtitles)
    if not result:
        return []
    return [{"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])]


# ========== 关键帧：v1 PPT 布局分析后端 ==========

def extract_slides_ppt_layout(video_path: str, out_dir: str, config: dict) -> list:
    """复用 v1 FrameExtractor（布局分析 + 场景变化 + 直方图去重）"""
    from src.extractors.frame_extractor import FrameExtractor
    extractor = FrameExtractor(config)
    frames = extractor.extract_frames(video_path, out_dir)
    # v1 输出 {"timestamp", "path"} → v2 结构 {"image", "time"}
    return [{"image": f["path"], "time": f["timestamp"]} for f in frames]


# ========== 翻译：v1 逐段后端 ==========

def translate_segments_v1(segments: list, workdir: str, config: dict) -> list:
    """
    复用 v1 TextTranslator（openai / deep-translator / argos 三引擎）。
    逐段翻译，结果写回段的 "text_zh" 字段（原文保留在 "text"）。
    """
    from src.processors.translator import TextTranslator
    translator = TextTranslator(config)
    result = translator.translate_segments(segments, workdir)
    by_start = {s.get("start", 0): s.get("translated", "")
                for s in result.get("segments", [])}
    out = []
    for seg in segments:
        seg = dict(seg)
        seg["text_zh"] = by_start.get(seg["start"], seg["text"])
        out.append(seg)
    return out


# ========== 文档：v1 模板生成器后端 ==========

def build_doc_legacy(segments: list, slides: list, video_info: dict,
                     out_dir: str, config: dict) -> str:
    """
    复用 v1 VisionDocGenerator（academic/minimal 模板，html/markdown/pdf）。
    输入沿用 v1 原生结构（ translated segments + frames ），
    对齐由 v1 生成器内部完成（±60s 滑窗），行为与 v1 完全一致。
    """
    from src.generators.vision_doc import VisionDocGenerator
    generator = VisionDocGenerator(config)
    translated_data = {
        "segments": [
            {"start": s["start"], "end": s["end"],
             "text": s["text"],
             "translated": s.get("text_zh", s["text"])}
            for s in segments
        ],
    }
    frames = [{"timestamp": s["time"], "path": s["image"]} for s in slides]
    v1_info = dict(video_info)
    v1_info["owner"] = {"name": video_info.get("owner", "")}
    return generator.generate(translated_data, frames, v1_info, out_dir)
