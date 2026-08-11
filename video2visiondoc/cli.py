"""
cli.py —— 命令行入口（v2 框架）

用法：
    python -m video2visiondoc <BV号或URL> [选项]

所有阶段的后端均可在 config.yaml 中切换；以下命令行参数是常用配置的
快捷覆盖。不传任何覆盖参数时，即为 v2 推荐配置
（与实战验证时激活的代码完全一致）。

示例：
    # 全流程 v2 默认
    python -m video2visiondoc BV13T3x69Eqz -o ./output

    # 领域提示词改善专有名词识别
    python -m video2visiondoc BV13T3x69Eqz \
        --prompt "Talk on sparse rewards in reinforcement learning"

    # 剔除演讲者镜头帧（第 2、3 帧，1 起计数）并输出 PDF
    python -m video2visiondoc BV13T3x69Eqz --exclude-frames 2 3 --pdf

    # 切换 v1 后端：yt-dlp 下载 + 布局分析抽帧 + 逐段翻译 + 模板文档
    python -m video2visiondoc BV13T3x69Eqz \
        --download yt-dlp --frames ppt_layout \
        --translate-mode per_segment --builder legacy
"""

import argparse
import json
import sys

from .config import load_config
from .pipeline import run


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="video2visiondoc",
        description="B 站视频 → 语音转写 → 翻译 → PPT 视觉文档（v2 框架，后端可切换）")
    p.add_argument("url", help="B 站视频 URL 或 BV 号")
    p.add_argument("-o", "--output", default=None, help="输出目录")
    p.add_argument("-c", "--config", default=None, help="config.yaml 路径")

    # v2 常用参数
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

    # 后端切换（对应 config.yaml 中的选择项）
    p.add_argument("--download", choices=["api", "yt-dlp"], default=None,
                   help="下载后端：api=v2直连(默认) / yt-dlp=v1")
    p.add_argument("--transcribe-mode", choices=["chunked", "standard"], default=None,
                   help="转写模式：chunked=v2分块(默认) / standard=v1整段")
    p.add_argument("--frames", choices=["interval_dhash", "ppt_layout"], default=None,
                   help="抽帧后端：interval_dhash=v2(默认) / ppt_layout=v1布局分析")
    p.add_argument("--align", choices=["per_slide", "window"], default=None,
                   help="对齐方式：per_slide=v2按页(默认) / window=v1滑窗")
    p.add_argument("--translate-mode", choices=["per_page", "per_segment"], default=None,
                   help="翻译模式：per_page=v2按页(默认) / per_segment=v1逐段")
    p.add_argument("--builder", choices=["slide", "legacy"], default=None,
                   help="文档后端：slide=v2(默认) / legacy=v1模板")

    # 流程控制（兼容 v1）
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
    if args.transcribe_mode:
        config["transcription"]["mode"] = args.transcribe_mode
    if args.frames:        config["frame_extraction"]["method"] = args.frames
    if args.align:         config["alignment"]["method"] = args.align
    if args.translate_mode:
        config["translation"]["mode"] = args.translate_mode
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
