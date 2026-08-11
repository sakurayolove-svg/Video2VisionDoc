"""
cli.py —— 命令行入口

用法：
    python -m video2visiondoc <BV号或URL> [选项]

所有阶段的模块均可在 config.yaml 中切换；以下命令行参数是常用配置的
快捷覆盖。不传任何覆盖参数时，即为推荐配置
（与实战验证时激活的代码完全一致）。

示例：
    # 全流程默认配置
    python -m video2visiondoc BV13T3x69Eqz -o ./output

    # 领域提示词改善专有名词识别
    python -m video2visiondoc BV13T3x69Eqz \
        --prompt "Talk on sparse rewards in reinforcement learning"

    # 剔除演讲者镜头帧（第 2、3 帧，1 起计数）并输出 PDF
    python -m video2visiondoc BV13T3x69Eqz --exclude-frames 2 3 --pdf

    # 切换备选模块：yt-dlp 下载 + 布局分析抽帧 + 逐段翻译 + 模板文档
    python -m video2visiondoc BV13T3x69Eqz \
        --download ytdlp --engine whisper --translator deep-translator \
        --frames ppt_layout --align window --builder legacy
"""

import argparse
import json
import sys

from .config import load_config
from .pipeline import run


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="video2visiondoc",
        description="B 站视频 → 语音转写 → 翻译 → PPT 视觉文档（模块可切换）")
    p.add_argument("url", help="B 站视频 URL 或 BV 号")
    p.add_argument("-o", "--output", default=None, help="输出目录")
    p.add_argument("-c", "--config", default=None, help="config.yaml 路径")

    # 常用参数
    p.add_argument("--model", default=None,
                   help="Whisper 模型 (tiny/base/small/medium/large-v3)")
    p.add_argument("--language", default=None, help="音频语言 (en/zh/...)")
    p.add_argument("--prompt", default=None, help="领域提示词")
    p.add_argument("--sample-interval", type=int, default=None, help="抽帧间隔秒数")
    p.add_argument("--hash-threshold", type=int, default=None, help="dHash 去重阈值")
    p.add_argument("--exclude-frames", type=int, nargs="*", default=None,
                   help="剔除的帧序号（1 起），如演讲者镜头")
    p.add_argument("--target-lang", default=None, help="目标语言")
    p.add_argument("--pdf", action="store_true", help="同时输出 PDF")

    # 模块切换（对应 config.yaml 中的选择项，每阶段单开关同级并列）
    p.add_argument("--download", choices=["api", "ytdlp"], default=None,
                   help="下载模块：api=API直连(默认) / ytdlp")
    p.add_argument("--engine", "-e",
                   choices=["chunked", "faster-whisper", "whisper", "openai-api"],
                   default=None,
                   help="转写引擎：chunked=分块(默认) / faster-whisper / whisper / openai-api=整段")
    p.add_argument("--translator",
                   choices=["llm", "openai", "deep-translator", "argos"],
                   default=None,
                   help="翻译引擎：llm=按页(默认) / openai / deep-translator / argos=逐段")
    p.add_argument("--frames",
                   choices=["interval_dhash", "ppt_layout", "scene_change",
                            "fixed_interval", "ocr_trigger"],
                   default=None,
                   help="抽帧模块：interval_dhash(默认) / ppt_layout=布局分析 / "
                        "scene_change=SSIM场景变化 / fixed_interval=固定间隔 / ocr_trigger=OCR触发")
    p.add_argument("--align", choices=["per_slide", "window"], default=None,
                   help="对齐方式：per_slide=按页(默认) / window=滑窗")
    p.add_argument("--builder", choices=["slide", "legacy"], default=None,
                   help="文档模块：slide=按页HTML(默认) / legacy=模板")

    # 流程控制
    p.add_argument("--use-subtitle", action="store_true",
                   help="优先使用 B 站已有字幕")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--audio", default=None)
    p.add_argument("--video", default=None)
    p.add_argument("--transcript", default=None, help="已有转录 JSON 文件")
    p.add_argument("--skip-translate", action="store_true")
    p.add_argument("--skip-frames", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)

    # 命令行覆盖配置
    if args.output:        config["output"]["directory"] = args.output
    if args.model:         config["transcription"]["model"] = args.model
    if args.language:      config["transcription"]["language"] = args.language
    if args.prompt is not None:
        config["transcription"]["initial_prompt"] = args.prompt
    if args.sample_interval:
        config["frame_extraction"]["sample_interval"] = args.sample_interval
    if args.hash_threshold:
        config["frame_extraction"]["hash_threshold"] = args.hash_threshold
    if args.exclude_frames is not None:
        config["alignment"]["exclude_frames"] = args.exclude_frames
    if args.target_lang:
        config["translation"]["target_language"] = args.target_lang
    if args.pdf:           config["vision_doc"]["pdf"] = True
    if args.download:      config["bilibili"]["method"] = args.download
    if args.engine:        config["transcription"]["engine"] = args.engine
    if args.translator:    config["translation"]["engine"] = args.translator
    if args.frames:        config["frame_extraction"]["method"] = args.frames
    if args.align:         config["alignment"]["method"] = args.align
    if args.builder:       config["vision_doc"]["builder"] = args.builder

    transcript = None
    if args.transcript:
        with open(args.transcript, encoding="utf-8") as f:
            transcript = json.load(f)
        if isinstance(transcript, dict):
            transcript = transcript.get("segments", [])

    doc = run(
        args.url, config,
        skip_download=args.skip_download,
        audio=args.audio, video=args.video,
        skip_transcribe=bool(args.transcript),
        transcript=transcript,
        skip_translate=args.skip_translate,
        skip_frames=args.skip_frames,
        use_subtitle=args.use_subtitle,
    )
    return doc


if __name__ == "__main__":
    sys.exit(main())
