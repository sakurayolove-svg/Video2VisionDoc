"""
video2visiondoc —— B 站视频 → 视觉文档的统一流水线框架

将 B 站演讲/课程视频转换为视觉文档的完整流水线，每个阶段提供
多个同级模块，用一个开关切换（默认项加粗，见 README）：

    下载（api / ytdlp）
    → 语音转写（chunked / faster-whisper / whisper / openai-api）
    → 关键帧提取（interval_dhash / ppt_layout）
    → 对齐（per_slide / window）
    → 翻译（llm / openai / deep-translator / argos）
    → 视觉文档（slide / legacy）

默认模块组合是在真实任务（BV13T3x69Eqz，35 分钟英文演讲，无字幕，
4GB 内存 CPU 容器）中验证过的实现；其余同级模块复制自仓库根目录
src/ 下的初版实现，与本包内默认模块并列可选。

说明：各模块采用懒加载，只有真正用到某阶段时才要求对应依赖
（如 faster-whisper 仅转写时需要，单独做关键帧/文档不需要）。
"""

__version__ = "2.0.0"

_LAZY = {
    "BiliDownloader": "downloader",
    "ChunkedTranscriber": "transcriber",
    "KeyframeExtractor": "keyframes",
    "SlideAligner": "aligner",
    "SlideTranslator": "translator",
    "VisionDocBuilder": "docbuilder",
    "load_config": "config",
    "run": "pipeline",
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        import importlib
        mod = importlib.import_module(f".{_LAZY[name]}", __package__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
