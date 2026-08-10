#!/usr/bin/env python3
"""
Video2VisionDoc: B站视频 → 语音转文字 → 翻译 → 视觉文档
一键生成学术/演讲视频的视觉文档

用法:
    python main.py --url "https://www.bilibili.com/video/BV13T3x69Eqz" --output ./output
    python main.py --url BV13T3x69Eqz --skip-download --audio ./my_audio.wav
    python main.py --url BV13T3x69Eqz --engine whisper --model large-v3
"""
import os
import sys
import argparse
import yaml
from pathlib import Path
from typing import Optional

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.extractors.bilibili import BiliVideoExtractor
from src.extractors.frame_extractor import FrameExtractor
from src.processors.transcriber import AudioTranscriber
from src.processors.translator import TextTranslator
from src.generators.vision_doc import VisionDocGenerator


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件"""
    if not os.path.exists(config_path):
        # 使用默认配置
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    parser.add_argument("--output", "-o", default="./output",
                        help="输出目录 (默认: ./output)")
    parser.add_argument("--config", "-c", default="config.yaml",
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
    parser.add_argument("--language", "-l", default="auto",
                        help="音频语言 (auto/en/zh/ja/...)")
    parser.add_argument("--use-subtitle", action="store_true",
                        help="优先使用B站已有字幕，无字幕再转录")
    parser.add_argument("--skip-transcribe", action="store_true",
                        help="跳过语音转文字")
    parser.add_argument("--transcript",
                        help="指定已有转录JSON文件路径")

    # 翻译控制
    parser.add_argument("--target-lang", "-t", default="zh-CN",
                        help="目标翻译语言 (默认: zh-CN)")
    parser.add_argument("--translator",
                        choices=["openai", "deep-translator", "argos"],
                        help="翻译引擎")
    parser.add_argument("--skip-translate", action="store_true",
                        help="跳过翻译")

    # 帧提取控制
    parser.add_argument("--skip-frames", action="store_true",
                        help="跳过关键帧提取")
    parser.add_argument("--frame-method",
                        choices=["scene_change", "fixed_interval", "ocr_trigger"],
                        help="关键帧提取方法")

    # 文档生成控制
    parser.add_argument("--format", "-f",
                        choices=["html", "markdown", "pdf"],
                        help="输出文档格式")
    parser.add_argument("--template",
                        choices=["default", "academic", "minimal"],
                        help="文档模板")

    # 其他
    parser.add_argument("--clean", action="store_true",
                        help="完成后清理临时文件")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")

    return parser.parse_args()


def main():
    args = parse_args()

    # 加载配置
    config = load_config(args.config)

    # 命令行参数覆盖配置文件
    if args.engine:
        config.setdefault("transcription", {})["engine"] = args.engine
    if args.model:
        config.setdefault("transcription", {})["model"] = args.model
    if args.language:
        config.setdefault("transcription", {})["language"] = args.language
    if args.target_lang:
        config.setdefault("translation", {})["target_language"] = args.target_lang
    if args.translator:
        config.setdefault("translation", {})["engine"] = args.translator
    if args.format:
        config.setdefault("vision_doc", {})["output_format"] = args.format
    if args.template:
        config.setdefault("vision_doc", {})["template"] = args.template
    if args.frame_method:
        config.setdefault("frame_extraction", {})["method"] = args.frame_method

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print(" Video2VisionDoc - B站视频视觉文档生成器")
    print("=" * 60)

    # ========== Step 1: 下载视频 ==========
    video_path = None
    audio_path = None
    video_info = {}
    bili_subtitles = None

    if not args.skip_download:
        print("\n[Step 1/5] 下载B站视频...")
        extractor = BiliVideoExtractor(config)
        try:
            result = extractor.download_video(args.url, str(temp_dir))
            video_path = result["video_path"]
            audio_path = result["audio_path"]
            video_info = result["info"]
            bili_subtitles = result.get("subtitles")
            print(f"✓ 视频: {video_path}")
            print(f"✓ 音频: {audio_path}")
            if bili_subtitles:
                print(f"✓ 发现B站字幕: {len(bili_subtitles)} 条")
        except Exception as e:
            print(f"✗ 下载失败: {e}")
            sys.exit(1)
    else:
        print("\n[Step 1/5] 跳过下载，使用已有文件...")
        if args.audio:
            audio_path = args.audio
        if args.video:
            video_path = args.video
        # 尝试解析BV号获取信息
        try:
            extractor = BiliVideoExtractor(config)
            bvid = extractor.parse_bvid(args.url)
            if bvid:
                video_info = extractor.get_video_info(bvid)
                bili_subtitles = extractor.get_subtitle(bvid, video_info.get("cid", 0))
        except Exception:
            pass

    # ========== Step 2: 语音转文字 ==========
    transcript_data = None

    if not args.skip_transcribe:
        if args.transcript:
            print(f"\n[Step 2/5] 加载已有转录文件: {args.transcript}")
            import json
            with open(args.transcript, "r", encoding="utf-8") as f:
                transcript_data = json.load(f)
        elif args.use_subtitle and bili_subtitles:
            print("\n[Step 2/5] 使用B站已有字幕...")
            transcriber = AudioTranscriber(config)
            transcript_data = transcriber.use_bili_subtitle(bili_subtitles)
            if transcript_data:
                print(f"✓ 使用字幕: {transcript_data.get('language', 'unknown')}")
            else:
                print("! B站无字幕，将使用语音转录")

        if not transcript_data and audio_path:
            print("\n[Step 2/5] 语音转文字...")
            transcriber = AudioTranscriber(config)
            try:
                transcript_data = transcriber.transcribe(audio_path, str(temp_dir))
                print(f"✓ 转录完成: {len(transcript_data.get('segments', []))} 片段")
                print(f"✓ 检测语言: {transcript_data.get('language', 'unknown')}")
            except Exception as e:
                print(f"✗ 转录失败: {e}")
                sys.exit(1)
    else:
        print("\n[Step 2/5] 跳过语音转文字")

    if not transcript_data:
        print("✗ 没有可用的转录数据")
        sys.exit(1)

    # ========== Step 3: 翻译 ==========
    translated_data = None

    if not args.skip_translate:
        print("\n[Step 3/5] 翻译文本...")
        translator = TextTranslator(config)
        try:
            translated_data = translator.translate_segments(
                transcript_data.get("segments", []),
                str(temp_dir)
            )
            print(f"✓ 翻译完成: {len(translated_data.get('segments', []))} 片段")
        except Exception as e:
            print(f"✗ 翻译失败: {e}")
            # 失败时使用原文
            translated_data = {
                "segments": [
                    {"start": s.get("start", 0), "end": s.get("end", 0),
                     "original": s.get("text", ""), "translated": s.get("text", "")}
                    for s in transcript_data.get("segments", [])
                ],
                "full_original": transcript_data.get("text", ""),
                "full_translated": transcript_data.get("text", ""),
            }
    else:
        print("\n[Step 3/5] 跳过翻译")
        translated_data = {
            "segments": [
                {"start": s.get("start", 0), "end": s.get("end", 0),
                 "original": s.get("text", ""), "translated": s.get("text", "")}
                for s in transcript_data.get("segments", [])
            ],
            "full_original": transcript_data.get("text", ""),
            "full_translated": transcript_data.get("text", ""),
        }

    # ========== Step 4: 提取关键帧 ==========
    frames = []

    if not args.skip_frames and video_path:
        print("\n[Step 4/5] 提取关键帧...")
        frame_extractor = FrameExtractor(config)
        try:
            frames = frame_extractor.extract_frames(video_path, str(temp_dir / "frames"))
            print(f"✓ 提取 {len(frames)} 帧")
        except Exception as e:
            print(f"✗ 帧提取失败: {e}")
    else:
        print("\n[Step 4/5] 跳过关键帧提取")

    # ========== Step 5: 生成视觉文档 ==========
    print("\n[Step 5/5] 生成视觉文档...")
    doc_generator = VisionDocGenerator(config)
    try:
        doc_path = doc_generator.generate(
            translated_data,
            frames,
            video_info,
            str(output_dir)
        )
        print(f"✓ 文档已生成: {doc_path}")
    except Exception as e:
        print(f"✗ 文档生成失败: {e}")
        sys.exit(1)

    # 清理
    if args.clean:
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print("\n[清理] 临时文件已删除")

    print("\n" + "=" * 60)
    print(" 全部完成!")
    print(f" 输出文件: {doc_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
