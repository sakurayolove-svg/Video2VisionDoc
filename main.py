#!/usr/bin/env python3
"""
Video2VisionDoc: B站视频 → 语音转文字 → 翻译 → 视觉文档
一键生成学术/演讲视频的视觉文档

本文件为兼容入口：保留 v1 的命令行接口，内部统一走
video2visiondoc 框架（pipeline.run）。各阶段后端由 config.yaml
中的选择项决定：

    bilibili.method:         api（v2 默认）/ yt-dlp（v1）
    transcription.mode:      chunked（v2 默认）/ standard（v1）
    frame_extraction.method: interval_dhash（v2 默认）/ ppt_layout（v1）
    alignment.method:        per_slide（v2 默认）/ window（v1）
    translation.mode:        per_page（v2 默认）/ per_segment（v1）
    vision_doc.builder:      slide（v2 默认）/ legacy（v1）

全部为 v2 默认值时，激活代码与 video2visiondoc 包完全一致；
v1 实现保留在 src/ 下，作为备选后端被复用。

用法:
    python main.py --url "https://www.bilibili.com/video/BV13T3x69Eqz" --output ./output
    python main.py --url BV13T3x69Eqz --skip-download --audio ./my_audio.wav
    python main.py --url BV13T3x69Eqz --engine whisper --model large-v3
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from video2visiondoc.config import load_config
from video2visiondoc.pipeline import run


def parse_args():
    parser = argparse.ArgumentParser(
        description="Video2VisionDoc: B站视频转视觉文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --url BV13T3x69Eqz
  %(prog)s --url "https://www.bilibili.com/video/BV13T3x69Eqz" --output ./output
  %(prog)s --url BV13T3x69Eqz --skip-frames  # 不提取关键帧
  %(prog)s --url BV13T3x69Eqz --engine faster-whisper --model large-v3
        """
    )

    parser.add_argument("--url", "-u", required=True,
                        help="B站视频URL或BV号")
    parser.add_argument("--output", "-o", default=None,
                        help="输出目录 (默认: ./output)")
    parser.add_argument("--config", "-c", default=None,
                        help="配置文件路径 (默认: config.yaml)")

    # 下载控制
    parser.add_argument("--skip-download", action="store_true",
                        help="跳过视频下载，使用已有音频文件")
    parser.add_argument("--audio", "-a",
                        help="指定已有音频文件路径 (与--skip-download配合使用)")
    parser.add_argument("--video",
                        help="指定已有视频文件路径 (与--skip-download配合使用)")

    # 转录控制
    parser.add_argument("--engine", "-e",
                        choices=["whisper", "faster-whisper", "openai-api"],
                        help="语音转文字引擎")
    parser.add_argument("--model", "-m",
                        help="Whisper模型大小 (tiny/base/small/medium/large-v3)")
    parser.add_argument("--language", "-l", default=None,
                        help="音频语言 (auto/en/zh/ja/...)")
    parser.add_argument("--use-subtitle", action="store_true",
                        help="优先使用B站已有字幕，无字幕再转录")
    parser.add_argument("--skip-transcribe", action="store_true",
                        help="跳过语音转文字")
    parser.add_argument("--transcript",
                        help="指定已有转录JSON文件路径")

    # 翻译控制
    parser.add_argument("--target-lang", "-t", default=None,
                        help="目标翻译语言 (默认: 中文)")
    parser.add_argument("--translator",
                        choices=["openai", "deep-translator", "argos"],
                        help="翻译引擎（v1 逐段模式）")
    parser.add_argument("--skip-translate", action="store_true",
                        help="跳过翻译")

    # 帧提取控制
    parser.add_argument("--skip-frames", action="store_true",
                        help="跳过关键帧提取")
    parser.add_argument("--frame-method",
                        choices=["scene_change", "fixed_interval", "ocr_trigger"],
                        help="关键帧提取方法（v1 布局分析后端）")

    # 文档生成控制
    parser.add_argument("--format", "-f",
                        choices=["html", "markdown", "pdf"],
                        help="输出文档格式（markdown/pdf 走 v1 模板生成器）")
    parser.add_argument("--template",
                        choices=["default", "academic", "minimal"],
                        help="文档模板（v1 模板生成器）")

    # 其他
    parser.add_argument("--clean", action="store_true",
                        help="完成后清理临时文件")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")

    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    # ===== 命令行参数映射到统一配置 =====
    if args.output:
        config["output"]["directory"] = args.output
    if args.engine:
        config["transcription"]["engine"] = args.engine
        # whisper / openai-api 引擎只有 v1 整段模式支持
        if args.engine != "faster-whisper":
            config["transcription"]["mode"] = "standard"
    if args.model:
        config["transcription"]["model"] = args.model
    if args.language:
        config["transcription"]["language"] = args.language
    if args.target_lang:
        config["translation"]["target_language"] = args.target_lang
    if args.translator:
        # 显式选择 v1 翻译引擎 → 逐段模式
        config["translation"]["engine"] = args.translator
        config["translation"]["mode"] = "per_segment"
    if args.frame_method:
        config["frame_extraction"]["method"] = "ppt_layout"
    if args.format:
        config["vision_doc"]["output_format"] = args.format
        if args.format in ("markdown", "pdf"):
            config["vision_doc"]["builder"] = "legacy"
    if args.template:
        config["vision_doc"]["template"] = args.template
        config["vision_doc"]["builder"] = "legacy"

    if args.verbose:
        import yaml
        print("[配置] 生效配置：")
        print(yaml.safe_dump(config, allow_unicode=True))

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
        skip_transcribe=args.skip_transcribe or bool(args.transcript),
        transcript=transcript,
        skip_translate=args.skip_translate,
        skip_frames=args.skip_frames,
        use_subtitle=args.use_subtitle,
    )

    if args.clean:
        workdir = Path(config["output"]["directory"]) / "work"
        if workdir.exists():
            shutil.rmtree(workdir)
            print("\n[清理] 临时文件已删除")


if __name__ == "__main__":
    main()
