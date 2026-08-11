"""
pipeline.py —— 统一流水线编排（v2 框架）

六个阶段，每个阶段单开关切换后端（实现均位于本包内，同级并列）：

    阶段     开关（config.yaml）            可选后端（粗体为 v2 默认）
    ─────────────────────────────────────────────────────────────
    1. 下载   bilibili.method               api / ytdlp
    2. 转写   transcription.engine          chunked / faster-whisper / whisper / openai-api
    3. 翻译   translation.engine            llm（按页） / openai / deep-translator / argos（逐段）
    4. 关键帧 frame_extraction.method       interval_dhash / ppt_layout
    5. 对齐   alignment.method              per_slide / window
    6. 文档   vision_doc.builder            slide / legacy

全部为默认值时，激活代码与 v2 实战验证版完全一致。

入口：
    - python -m video2visiondoc   → cli.py   → run()
    - python main.py（仓库根目录） → 兼容入口 → run()
"""

from pathlib import Path

from . import backends


def run(url: str, config: dict,
        skip_download: bool = False, audio: str = None, video: str = None,
        skip_transcribe: bool = False, transcript: list = None,
        skip_translate: bool = False, skip_frames: bool = False,
        use_subtitle: bool = False) -> str:
    """执行完整流水线，返回生成的文档路径。"""
    outdir = Path(config["output"]["directory"])
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = outdir / "work"
    workdir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" Video2VisionDoc —— B 站视频视觉文档生成器")
    print("=" * 60)

    # ================= Step 1: 下载 =================
    print("\n[Step 1/6] 下载 B 站视频")
    if skip_download:
        if not audio and not video:
            raise ValueError("--skip-download 需要同时提供 --audio 或 --video")
        from .downloader import BiliDownloader
        result = {"info": {"bvid": BiliDownloader.parse_bvid(url),
                           "title": BiliDownloader.parse_bvid(url),
                           "duration": 0, "owner": ""},
                  "video_path": video, "audio_path": audio}
        try:  # 尽量补全视频信息
            result["info"] = BiliDownloader(str(workdir)).get_video_info(
                result["info"]["bvid"])
        except Exception:
            pass
    else:
        result = backends.download(url, str(workdir), config)
    info = result["info"]
    subtitles = result.get("subtitles")

    # B 站字幕获取（复用 v1 实现，与下载后端无关）
    if use_subtitle and not subtitles:
        try:
            subtitles = backends.get_bili_subtitles(
                info["bvid"], info.get("cid") or 0, config)
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
            segments = backends.transcribe(result["audio_path"],
                                           str(workdir), config)
    else:
        segments = backends.transcribe(result["audio_path"],
                                       str(workdir), config)

    # ================= Step 3: 翻译 =================
    # llm（v2 默认）：按页翻译，在对齐后执行；
    # openai / deep-translator / argos（v1）：逐段翻译，在抽帧前执行。
    trans_engine = config["translation"].get("engine", "llm")
    per_page = trans_engine == "llm"
    if not skip_translate and not per_page:
        print(f"\n[Step 3/6] 翻译（逐段 · {trans_engine}，v1）")
        segments = backends.translate_segments(segments, str(workdir), config)
    else:
        print(f"\n[Step 3/6] 翻译（按页 · llm，将在对齐后执行）")

    # ================= Step 4: 关键帧 =================
    print("\n[Step 4/6] 提取 PPT 关键帧")
    if skip_frames or not result.get("video_path"):
        slides = []
        print("  跳过（纯文本模式）")
    else:
        slides = backends.extract_slides(result["video_path"],
                                         str(workdir / "slides"), config)

    # ================= Step 5: 对齐 =================
    print("\n[Step 5/6] 转写文本与画面对齐")
    blocks = backends.align(slides, segments, config)
    print(f"  共 {len(blocks)} 页/块")

    if not skip_translate and per_page:
        blocks = backends.translate_blocks(blocks, str(workdir), config)

    # ================= Step 6: 生成文档 =================
    print("\n[Step 6/6] 生成视觉文档")
    doc_path = backends.build_doc(blocks, segments, slides, info,
                                  str(outdir), config)

    print("\n" + "=" * 60)
    print(f" 全部完成！输出: {doc_path}")
    print("=" * 60)
    return doc_path
