"""
keyframes.py —— PPT 关键帧提取（固定间隔抽帧 + dHash 感知哈希去重）

为什么不用纯场景变化检测（ffmpeg select=gt(scene,x)）：
    - 阈值难调：高了漏掉版式相近的翻页，低了把演讲者镜头切进来；
    - 静态 PPT 封面/长停留页可能完全检测不到。
实战经验（35 分钟演讲验证）：
    - 每 10 秒均匀抽一帧（ffmpeg fps=1/10），保证不遗漏任何页面；
    - 用 dHash（16×16，256 bit）计算相邻“去重锚点”的汉明距离，
      距离超过阈值（默认 40/256）才保留新帧；
    - 演讲者镜头与 PPT 画面差异极大，会被自然区分为不同帧，
      后续人工/规则剔除即可；同一个 PPT 停留数分钟只保留一帧。

依赖：ffmpeg、Pillow、numpy。
"""

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def _dhash(path: str, size: int = 16) -> np.ndarray:
    """差值感知哈希：比较相邻像素的亮度大小关系"""
    im = Image.open(path).convert("L").resize((size + 1, size))
    a = np.asarray(im, dtype=np.int16)
    return (a[:, 1:] > a[:, :-1]).flatten()


def _hamming(h1: np.ndarray, h2: np.ndarray) -> int:
    return int(np.count_nonzero(h1 != h2))


class KeyframeExtractor:
    """固定间隔抽帧 + dHash 去重的关键帧提取器"""

    def __init__(self, sample_interval: int = 10, hash_threshold: int = 40):
        """
        sample_interval: 抽帧间隔（秒），默认 10s；
                         演讲视频翻页 rarely 快于 10s，足够细密。
        hash_threshold:  dHash 汉明距离阈值（满分 256），默认 40；
                         调小保留更多帧（可能保留相近页），调大去重更狠。
        """
        self.sample_interval = sample_interval
        self.hash_threshold = hash_threshold

    def extract(self, video_path: str, out_dir: str) -> list:
        """
        提取去重后的关键帧。
        返回 slides: [{"image": 路径, "time": 秒}, ...]，按时间升序。
        图片保存在 out_dir 下，命名为 slide_01.jpg, slide_02.jpg ...
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = out_dir / "_raw"
        raw_dir.mkdir(exist_ok=True)

        # 1. 均匀抽帧
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-vf", f"fps=1/{self.sample_interval}",
             str(raw_dir / "f_%04d.jpg")],
            check=True, capture_output=True)
        frames = sorted(raw_dir.glob("f_*.jpg"))
        if not frames:
            raise RuntimeError("抽帧失败，未产生任何图片")

        # 2. dHash 去重（与上一个“保留帧”比较，而不是与相邻帧比较，
        #    避免画面缓变时累积漂移导致误保留）
        hashes = [_dhash(str(f)) for f in frames]
        kept = [frames[0]]
        last_kept_hash = hashes[0]
        for i in range(1, len(frames)):
            if _hamming(hashes[i], last_kept_hash) > self.hash_threshold:
                kept.append(frames[i])
                last_kept_hash = hashes[i]

        # 3. 重命名输出并记录时间戳（第 i 张抽帧对应时间 ≈ i × interval）
        slides = []
        for idx, f in enumerate(kept):
            out_path = out_dir / f"slide_{idx + 1:02d}.jpg"
            Image.open(f).save(out_path, quality=90)
            frame_no = int(f.stem.split("_")[1])  # f_0001 → 1
            slides.append({
                "image": str(out_path),
                "time": (frame_no - 1) * self.sample_interval,
            })

        print(f"  抽帧 {len(frames)} 张 → 去重后 {len(slides)} 张")
        return slides
