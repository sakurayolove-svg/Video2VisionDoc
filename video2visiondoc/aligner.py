"""
aligner.py —— 按 PPT 页对齐转写文本

核心思想（与初版“60 秒滑动窗口配对”不同）：
    每页 PPT 在屏幕上停留一个时间段 [t_i, t_{i+1})，
    演讲者在该页期间讲的所有内容，天然属于这页 PPT。
    因此以关键帧出现时间为边界，把转写段划分成“每页一块”。

这样做的好处：
    1. 翻译粒度从“一句一段”变为“一页一段”，上下文完整，
       LLM 翻译时指代、术语一致性好得多；
    2. 视觉文档的结构天然是“一页 PPT + 一段讲解”，
       与读者看演讲录像的认知方式一致。

可以传入 exclude 参数剔除已知的非 PPT 帧（如开场演讲者镜头）。
"""


class SlideAligner:
    """把转写段按关键帧时间窗归组"""

    def __init__(self, exclude: list = None):
        """
        exclude: 需要剔除的帧下标列表（0 起），
                 例如视频中穿插的演讲者纯镜头帧。
                 被剔除帧的时间窗会并入前一页。
        """
        self.exclude = set(exclude or [])

    def align(self, slides: list, segments: list) -> list:
        """
        slides:   KeyframeExtractor 的输出 [{"image":..., "time":...}, ...]
        segments: ChunkedTranscriber 的输出 [{"start","end","text"}, ...]
        返回 blocks: [{
            "index":   页码（1 起，剔除后重新编号）
            "image":   PPT 图片路径
            "t_start": 时间窗起点（秒）
            "t_end":   时间窗终点（秒）
            "text":    该页时间窗内的全部转写文本
        }, ...]
        """
        # 先剔除指定帧
        kept = [s for i, s in enumerate(slides) if i not in self.exclude]
        if not kept:
            raise ValueError("剔除后没有剩余帧")

        blocks = []
        n = len(kept)
        for i, slide in enumerate(kept):
            t_start = slide["time"]
            t_end = kept[i + 1]["time"] if i + 1 < n else float("inf")
            window = [seg for seg in segments
                      if t_start <= seg["start"] < t_end]
            blocks.append({
                "index": i + 1,
                "image": slide["image"],
                "t_start": t_start,
                "t_end": t_end if t_end != float("inf") else None,
                "text": " ".join(seg["text"] for seg in window).strip(),
                # 若段已被逐段翻译（v1 per_segment 模式），译文随窗带走
                "text_zh": " ".join(seg.get("text_zh", seg["text"])
                                    for seg in window).strip(),
            })
        return blocks


def align_window(slides: list, segments: list, window_seconds: int = 60) -> list:
    """
    v1 风格对齐（备选后端）：每帧配对 ±window 秒内的转写段。
    与 src/generators/vision_doc.py 的 _align_frames_with_segments 语义一致，
    归一化为 v2 的 blocks 结构。
    """
    blocks = []
    for i, slide in enumerate(slides):
        t = slide["time"]
        window = [seg for seg in segments
                  if abs(seg.get("start", 0) - t) < window_seconds]
        blocks.append({
            "index": i + 1,
            "image": slide["image"],
            "t_start": t,
            "t_end": None,
            "text": " ".join(seg["text"] for seg in window).strip(),
            "text_zh": " ".join(seg.get("text_zh", seg["text"])
                                for seg in window).strip(),
        })
    return blocks
