"""
video2visiondoc —— 推荐流水线（v2）

将 B 站演讲/课程视频转换为视觉文档的完整流水线：
    下载（B站 API 直连）
    → 语音转写（faster-whisper 分块，防 OOM）
    → 关键帧提取（固定间隔抽帧 + dHash 去重）
    → 按页对齐（每页 PPT 一个时间窗）
    → 按页翻译（OpenAI 兼容 API，上下文连贯）
    → 视觉文档（自包含 HTML，可选 PDF）

本包是在真实任务（BV13T3x69Eqz，35 分钟英文演讲，无字幕，4GB 内存
CPU 容器）中验证过的实现，作为仓库的推荐结构；仓库根目录下的
main.py 与 src/ 为初版实现，作为补充保留。

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
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        import importlib
        mod = importlib.import_module(f".{_LAZY[name]}", __package__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
