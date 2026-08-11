"""
backends.py —— 后端注册表（所有实现同级并列，单开关切换）

所有模块实现都位于 video2visiondoc 包内，同级并列：

    - downloader / transcriber / keyframes / aligner /
      translator / docbuilder（默认模块，真实任务验证）
    - downloader_ytdlp / transcriber_standard / keyframes_ppt_layout /
      keyframes_methods / vlm_ppt_detector / translator_engines /
      docbuilder_legacy（复制自 src/ 及初版提交的同级备选模块）

每个阶段只有一个选择开关，选 whisper 之类的细粒度引擎不需要
再额外切换任何其他开关：

    bilibili.method:          api（默认） | ytdlp
    transcription.engine:     chunked（默认） | faster-whisper | whisper | openai-api
    translation.engine:       llm（默认，按页） | openai | deep-translator | argos
    frame_extraction.method:  interval_dhash（默认） | ppt_layout |
                              scene_change | fixed_interval | ocr_trigger
    alignment.method:         per_slide（默认） | window
    vision_doc.builder:       slide（默认） | legacy

本模块只做归一化包装（统一各模块的输入输出数据结构），
不修改任何模块实现代码。当全部使用默认值时，激活代码与
真实任务验证过的实现完全一致。
"""

from pathlib import Path

from .downloader import BiliDownloader
from .transcriber import ChunkedTranscriber
from .keyframes import KeyframeExtractor
from .aligner import SlideAligner, align_window
from .translator import SlideTranslator
from .docbuilder import VisionDocBuilder


# ========== 阶段 1：下载 ==========

def download(url: str, workdir: str, config: dict) -> dict:
    """统一下载入口。返回 {info, video_path, audio_path, subtitles?}"""
    method = config["bilibili"].get("method", "api")
    if method == "ytdlp":
        print("  后端: yt-dlp")
        from .downloader_ytdlp import BiliVideoExtractor
        result = BiliVideoExtractor(config).download_video(url, workdir)
        info = result["info"]
        return {
            "info": {
                "bvid": result["bvid"], "aid": info.get("aid"),
                "cid": result.get("cid"), "title": result["title"],
                "duration": result.get("duration", 0),
                "owner": info.get("owner", {}).get("name", ""),
                "desc": info.get("desc", ""),
            },
            "video_path": result["video_path"],
            "audio_path": result["audio_path"],
            "subtitles": result.get("subtitles"),
        }
    print("  后端: API 直连（默认）")
    return BiliDownloader(workdir).download(url)


def get_bili_subtitles(bvid: str, cid: int, config: dict) -> list:
    """B 站字幕获取（两种下载模块均可使用）"""
    from .downloader_ytdlp import BiliVideoExtractor
    return BiliVideoExtractor(config).get_subtitle(bvid, cid)


# ========== 阶段 2：转写 ==========

def transcribe(audio_path: str, workdir: str, config: dict) -> list:
    """统一转写入口。返回 [{"start","end","text"}, ...]"""
    tr_cfg = config["transcription"]
    engine = tr_cfg.get("engine", "chunked")

    if engine == "chunked":
        print("  后端: 分块转写（默认，防 OOM）")
        return ChunkedTranscriber(
            model_size=tr_cfg.get("model", "small"),
            device=tr_cfg.get("device", "cpu"),
            compute_type=tr_cfg.get("compute_type", "int8"),
            chunk_seconds=tr_cfg.get("chunk_seconds", 300),
            beam_size=tr_cfg.get("beam_size", 3),
            language=tr_cfg.get("language", "en"),
            initial_prompt=tr_cfg.get("initial_prompt", ""),
        ).transcribe(audio_path, workdir)

    # 细粒度整段引擎：faster-whisper / whisper / openai-api
    print(f"  后端: 整段转写 · {engine}")
    from .transcriber_standard import AudioTranscriber
    result = AudioTranscriber(config).transcribe(audio_path, workdir)
    return [{"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])]


def transcribe_via_bili_subtitle(subtitles: list, config: dict) -> list:
    """复用 B 站已有字幕"""
    from .transcriber_standard import AudioTranscriber
    result = AudioTranscriber(config).use_bili_subtitle(subtitles)
    if not result:
        return []
    return [{"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])]


# ========== 阶段 3：翻译 ==========

def translate_segments(segments: list, workdir: str, config: dict) -> list:
    """
    逐段翻译（engine = openai / deep-translator / argos）。
    译文写入段的 "text_zh" 字段。
    """
    from .translator_engines import TextTranslator
    result = TextTranslator(config).translate_segments(segments, workdir)
    by_start = {s.get("start", 0): s.get("translated", "")
                for s in result.get("segments", [])}
    out = []
    for seg in segments:
        seg = dict(seg)
        seg["text_zh"] = by_start.get(seg["start"], seg["text"])
        out.append(seg)
    return out


def translate_blocks(blocks: list, workdir: str, config: dict) -> list:
    """按页翻译（engine = llm，默认）"""
    tr_cfg = config["translation"]
    return SlideTranslator(
        target_lang=tr_cfg.get("target_language", "中文"),
        preserve_terms=tr_cfg.get("preserve_terms"),
    ).translate_blocks(blocks, workdir)


# ========== 阶段 4：关键帧 ==========

def extract_slides(video_path: str, out_dir: str, config: dict) -> list:
    """统一抽帧入口。返回 [{"image","time"}, ...]"""
    fe_cfg = config["frame_extraction"]
    method = fe_cfg.get("method", "interval_dhash")
    if method == "ppt_layout":
        print("  后端: PPT 布局分析")
        from .keyframes_ppt_layout import FrameExtractor
        frames = FrameExtractor(config).extract_frames(video_path, out_dir)
        return [{"image": f["path"], "time": f["timestamp"]} for f in frames]
    if method in ("scene_change", "fixed_interval", "ocr_trigger"):
        label = {"scene_change": "场景变化（SSIM）",
                 "fixed_interval": "固定间隔",
                 "ocr_trigger": "OCR 触发"}[method]
        print(f"  后端: {label}")
        from .keyframes_methods import FrameExtractor
        frames = FrameExtractor(config).extract_frames(video_path, out_dir)
        return [{"image": f["path"], "time": f["timestamp"]} for f in frames]
    print("  后端: 均匀抽帧 + dHash 去重（默认）")
    return KeyframeExtractor(
        sample_interval=fe_cfg.get("sample_interval", 10),
        hash_threshold=fe_cfg.get("hash_threshold", 40),
    ).extract(video_path, out_dir)


# ========== 阶段 5：对齐 ==========

def align(slides: list, segments: list, config: dict) -> list:
    """统一对齐入口。返回 blocks（见 aligner.py）"""
    al_cfg = config["alignment"]
    method = al_cfg.get("method", "per_slide")
    if method == "window" or not slides:
        print("  后端: ±60s 滑窗")
        return align_window(slides, segments,
                            al_cfg.get("window_seconds", 60))
    print("  后端: 按 PPT 页时间窗（默认）")
    exclude = [i - 1 for i in al_cfg.get("exclude_frames", [])]
    return SlideAligner(exclude=exclude).align(slides, segments)


# ========== 阶段 6：文档 ==========

def build_doc(blocks, segments, slides, video_info: dict,
              out_dir: str, config: dict) -> str:
    """统一文档入口"""
    doc_cfg = config["vision_doc"]
    builder = doc_cfg.get("builder", "slide")
    if builder == "legacy":
        print("  后端: 模板生成器（HTML/MD/PDF）")
        from .docbuilder_legacy import VisionDocGenerator
        translated_data = {
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"],
                 "translated": s.get("text_zh", s["text"])}
                for s in segments
            ],
        }
        frames = [{"timestamp": s["time"], "path": s["image"]}
                  for s in slides]
        info = dict(video_info)
        info["owner"] = {"name": video_info.get("owner", "")}
        return VisionDocGenerator(config).generate(
            translated_data, frames, info, out_dir)

    print("  后端: 按页视觉文档（默认）")
    safe = "".join(c if c.isalnum() or c in " _-" else "_"
                   for c in video_info.get("title", "doc"))[:50]
    vb = VisionDocBuilder()
    doc_path = vb.build_html(blocks, video_info,
                             str(Path(out_dir) / f"{safe}_视觉文档.html"))
    if doc_cfg.get("pdf"):
        vb.build_pdf(doc_path, str(Path(out_dir) / f"{safe}_视觉文档.pdf"))
    return doc_path
