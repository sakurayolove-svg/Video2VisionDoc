"""
pipeline.py —— 统一流水线编排（v2 框架）

六个阶段，每个阶段按 config 选择后端：

    阶段          v2 默认后端（本包实现）        v1 备选后端（src/ 复用）
    ─────────────────────────────────────────────────────────────────
    1. 下载       bilibili.method=api           yt-dlp
    2. 转写       transcription.mode=chunked    standard（整段，多引擎）
    3. 翻译       translation.mode=per_page     per_segment（逐段，3 引擎）
    4. 关键帧     method=interval_dhash         ppt_layout（布局分析）
    5. 对齐       alignment.method=per_slide    window（±60s 滑窗）
    6. 文档       vision_doc.builder=slide      legacy（模板生成器）

当全部使用 v2 默认值时，激活的代码与本包 v2 实现完全一致
（即 BV13T3x69Eqz 实战验证时运行的代码路径）。

入口：
    - python -m video2visiondoc   → cli.py      → run()
    - python main.py（仓库根目录） → 兼容入口    → run()
"""

from pathlib import Path

from .downloader import BiliDownloader
from .transcriber import ChunkedTranscriber
from .keyframes import KeyframeExtractor
from .aligner import SlideAligner, align_window
from .translator import SlideTranslator
from .docbuilder import VisionDocBuilder
from . import backends


def run(url: str, config: dict,
        skip_download: bool = False, audio: str = None, video: str = None,
        skip_transcribe: bool = False, transcript: list = None,
        skip_translate: bool = False, skip_frames: bool = False,
        use_subtitle: bool = False) -> str:
    """
    执行完整流水线，返回生成的文档路径。
    config 结构见 config.py 的 DEFAULT_CONFIG。
    """
    outdir = Path(config["output"]["directory"])
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / "work"
    workdir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" Video2VisionDoc —— B 站视频视觉文档生成器")
    print("=" * 60)

    # ================= Step 1: 下载 =================
    print("\n[Step 1/6] 下载 B 站视频")
    method = config["bilibili"].get("method", "api")
    if skip_download:
        if not audio and not video:
            raise ValueError("--skip-download 需要同时提供 --audio 或 --video")
        result = {"info": {"bvid": BiliDownloader.parse_bvid(url),
                           "title": BiliDownloader.parse_bvid(url),
                           "duration": 0, "owner": ""},
                  "video_path": video, "audio_path": audio}
        try:  # 尽量补全视频信息
            result["info"] = BiliDownloader(str(workdir)).get_video_info(
                result["info"]["bvid"])
        except Exception:
            pass
    elif method == "yt-dlp":
        print(f"  后端: yt-dlp（v1 复用）")
        result = backends.download_via_ytdlp(url, str(workdir), config)
    else:
        print(f"  后端: API 直连（v2 默认）")
        result = BiliDownloader(str(workdir)).download(url)
    info = result["info"]
    subtitles = result.get("subtitles")

    # 无论哪种下载后端，都可复用 v1 的 B 站字幕获取
    if use_subtitle and not subtitles:
        try:
            from src.extractors.bilibili import BiliVideoExtractor
            subtitles = BiliVideoExtractor(config).get_subtitle(
                info["bvid"], info.get("cid") or 0)
        except Exception:
            subtitles = None

    # ================= Step 2: 语音转写 =================
    print("\n[Step 2/6] 语音转写")
    if transcript is not None:
        segments = transcript
        print(f"  使用已有转录: {len(segments)} 段")
    elif skip_transcribe:
        raise ValueError("--skip-transcribe 需要通过 --transcript 提供转录文件")
    elif use_subtitle and subtitles:
        print("  后端: B 站已有字幕（v1 复用）")
        segments = backends.transcribe_via_bili_subtitle(subtitles, config)
        if not segments:
            print("  字幕不可用，回退到语音转写")
            segments = _transcribe(result["audio_path"], workdir, config)
    else:
        segments = _transcribe(result["audio_path"], workdir, config)

    # ================= Step 3: 翻译（逐段模式在抽帧前） =================
    trans_mode = config["translation"].get("mode", "per_page")
    if not skip_translate and trans_mode == "per_segment":
        print("\n[Step 3/6] 翻译（逐段，v1 后端复用）")
        segments = backends.translate_segments_v1(segments, str(workdir), config)
    else:
        print(f"\n[Step 3/6] 翻译（按页模式，将在对齐后执行）")

    # ================= Step 4: 关键帧 =================
    print("\n[Step 4/6] 提取 PPT 关键帧")
    fe_cfg = config["frame_extraction"]
    fe_method = fe_cfg.get("method", "interval_dhash")
    if skip_frames or not result.get("video_path"):
        slides = []
        print("  跳过（纯文本模式）")
    elif fe_method == "ppt_layout":
        print("  后端: PPT 布局分析（v1 复用）")
        slides = backends.extract_slides_ppt_layout(
            result["video_path"], str(workdir / "slides"), config)
    else:
        print("  后端: 均匀抽帧 + dHash 去重（v2 默认）")
        slides = KeyframeExtractor(
            sample_interval=fe_cfg.get("sample_interval", 10),
            hash_threshold=fe_cfg.get("hash_threshold", 40),
        ).extract(result["video_path"], str(workdir / "slides"))

    # ================= Step 5: 对齐 =================
    print("\n[Step 5/6] 转写文本与画面对齐")
    al_cfg = config["alignment"]
    al_method = al_cfg.get("method", "per_slide")
    exclude = [i - 1 for i in al_cfg.get("exclude_frames", [])]
    if al_method == "window" or not slides:
        print("  后端: ±60s 滑窗（v1 语义）")
        blocks = align_window(slides, segments,
                              al_cfg.get("window_seconds", 60))
    else:
        print("  后端: 按 PPT 页时间窗（v2 默认）")
        blocks = SlideAligner(exclude=exclude).align(slides, segments)
    print(f"  共 {len(blocks)} 页/块")

    # 按页翻译（v2 默认）：对齐后以页为粒度翻译
    if not skip_translate and trans_mode == "per_page":
        tr_cfg = config["translation"]
        translator = SlideTranslator(
            target_lang=tr_cfg.get("target_language", "中文"),
            preserve_terms=tr_cfg.get("preserve_terms"),
        )
        blocks = translator.translate_blocks(blocks, str(workdir))

    # ================= Step 6: 生成文档 =================
    print("\n[Step 6/6] 生成视觉文档")
    doc_cfg = config["vision_doc"]
    builder = doc_cfg.get("builder", "slide")
    if builder == "legacy":
        print("  后端: 模板生成器（v1 复用）")
        doc_path = backends.build_doc_legacy(
            segments, slides, info, str(outdir), config)
    else:
        print("  后端: 按页视觉文档（v2 默认）")
        safe = "".join(c if c.isalnum() or c in " _-" else "_"
                       for c in info.get("title", "doc"))[:50]
        vb = VisionDocBuilder()
        doc_path = vb.build_html(blocks, info,
                                 str(outdir / f"{safe}_视觉文档.html"))
        if doc_cfg.get("pdf"):
            vb.build_pdf(doc_path, str(outdir / f"{safe}_视觉文档.pdf"))

    print("\n" + "=" * 60)
    print(f" 全部完成！输出: {doc_path}")
    print("=" * 60)
    return doc_path


def _transcribe(audio_path: str, workdir: Path, config: dict) -> list:
    """转写后端分发"""
    tr_cfg = config["transcription"]
    mode = tr_cfg.get("mode", "chunked")
    if mode == "standard":
        print("  后端: 整段转写（v1 复用，多引擎）")
        return backends.transcribe_standard(audio_path, str(workdir), config)
    print("  后端: 分块转写（v2 默认，防 OOM）")
    return ChunkedTranscriber(
        model_size=tr_cfg.get("model", "small"),
        device=tr_cfg.get("device", "cpu"),
        compute_type=tr_cfg.get("compute_type", "int8"),
        chunk_seconds=tr_cfg.get("chunk_seconds", 300),
        beam_size=tr_cfg.get("beam_size", 3),
        language=tr_cfg.get("language", "en"),
        initial_prompt=tr_cfg.get("initial_prompt", ""),
    ).transcribe(audio_path, str(workdir))
