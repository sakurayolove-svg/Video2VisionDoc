"""
cli.py —— 命令行入口

用法：
    python -m video2visiondoc <BV号或URL> [选项]

示例：
    # 全流程（需要 LLM_API_KEY 才会翻译，否则保留英文）
    python -m video2visiondoc BV13T3x69Eqz -o ./output

    # 指定 Whisper 模型与领域提示词（改善专有名词识别）
    python -m video2visiondoc BV13T3x69Eqz --model small \
        --prompt "Talk on sparse rewards in reinforcement learning"

    # 剔除第 2、3 帧（演讲者镜头），下标从 1 开始
    python -m video2visiondoc BV13T3x69Eqz --exclude-frames 2 3

    # 同时输出 PDF（需要 playwright 或 weasyprint）
    python -m video2visiondoc BV13T3x69Eqz --pdf
"""

import argparse
import sys
from pathlib import Path

from .downloader import BiliDownloader
from .transcriber import ChunkedTranscriber
from .keyframes import KeyframeExtractor
from .aligner import SlideAligner
from .translator import SlideTranslator
from .docbuilder import VisionDocBuilder


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="video2visiondoc",
        description="B 站视频 → 语音转写 → 按页翻译 → PPT 视觉文档")
    p.add_argument("url", help="B 站视频 URL 或 BV 号")
    p.add_argument("-o", "--output", default="./output", help="输出目录")
    p.add_argument("--model", default="small",
                   help="Whisper 模型 (tiny/base/small/medium/large-v3)，"
                        "4GB 内存建议 ≤ small")
    p.add_argument("--language", default="en", help="音频语言 (en/zh/...)")
    p.add_argument("--prompt", default="",
                   help="领域提示词，改善专有名词识别")
    p.add_argument("--sample-interval", type=int, default=10,
                   help="抽帧间隔秒数 (默认 10)")
    p.add_argument("--hash-threshold", type=int, default=40,
                   help="dHash 去重阈值，满分 256 (默认 40)")
    p.add_argument("--exclude-frames", type=int, nargs="*", default=[],
                   help="需要剔除的帧序号（1 起），如演讲者镜头")
    p.add_argument("--target-lang", default="中文", help="目标语言")
    p.add_argument("--pdf", action="store_true", help="同时输出 PDF")
    p.add_argument("--keep-temp", action="store_true",
                   help="保留临时文件（默认保留，便于断点续跑；此参数仅为对称性保留）")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    workdir = Path(args.output) / "work"
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" video2visiondoc —— B 站视频视觉文档生成器（推荐流水线）")
    print("=" * 60)

    # Step 1: 下载
    print("\n[Step 1/6] 下载 B 站视频")
    dl = BiliDownloader(str(workdir))
    result = dl.download(args.url)
    info = result["info"]

    # Step 2: 语音转写（分块，防 OOM）
    print("\n[Step 2/6] 语音转写（分块模式）")
    transcriber = ChunkedTranscriber(
        model_size=args.model,
        language=args.language,
        initial_prompt=args.prompt,
    )
    segments = transcriber.transcribe(result["audio_path"], str(workdir))

    # Step 3: 关键帧提取（均匀抽帧 + dHash 去重）
    print("\n[Step 3/6] 提取 PPT 关键帧")
    extractor = KeyframeExtractor(
        sample_interval=args.sample_interval,
        hash_threshold=args.hash_threshold,
    )
    slides = extractor.extract(result["video_path"], str(workdir / "slides"))

    # Step 4: 按页对齐
    print("\n[Step 4/6] 按 PPT 页对齐转写文本")
    exclude = [i - 1 for i in args.exclude_frames]  # 转为 0 起下标
    aligner = SlideAligner(exclude=exclude)
    blocks = aligner.align(slides, segments)
    print(f"  共 {len(blocks)} 页，"
          f"总字数 {sum(len(b['text'].split()) for b in blocks)}")

    # Step 5: 按页翻译
    print("\n[Step 5/6] 翻译")
    translator = SlideTranslator(target_lang=args.target_lang)
    blocks = translator.translate_blocks(blocks, str(workdir))

    # Step 6: 生成视觉文档
    print("\n[Step 6/6] 生成视觉文档")
    builder = VisionDocBuilder()
    safe = "".join(c if c.isalnum() or c in " _-" else "_"
                   for c in info["title"])[:50]
    html_path = builder.build_html(
        blocks, info, str(outdir / f"{safe}_视觉文档.html"))
    if args.pdf:
        builder.build_pdf(html_path, str(outdir / f"{safe}_视觉文档.pdf"))

    print("\n" + "=" * 60)
    print(" 全部完成！")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
