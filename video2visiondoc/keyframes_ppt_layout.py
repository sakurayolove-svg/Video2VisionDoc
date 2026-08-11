"""
【v1 后端：PPT 布局分析抽帧】
本文件复制自 src/extractors/frame_extractor.py（v1 初版实现），纳入 video2visiondoc 框架
作为同级可切换后端。原始文件保留于 src/ 未作修改。
"""
"""
关键帧/PPT画面提取器 v4 — 基于布局分析的PPT智能定位

核心改进：
1. 不再假设"视频开头=PPT第一页"
2. 用布局分析算法计算每帧的"PPT分数"
3. 找到PPT真正开始的位置（前60秒内分数首次超过阈值）
4. 从该位置开始提取关键帧，同时保留所有高分数帧
5. 支持VLM作为备选方案

PPT布局特征（与片头/过渡/演讲者的区别）：
- 文字密度适中（5-60%）
- 结构化布局：标题区(上) + 内容区(中) + 留白(下)
- 水平边缘密集（文字行）
- 前景背景对比强烈
- 背景均匀（纯色/渐变）
"""
import cv2
import numpy as np
import subprocess
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional


def compute_ppt_score(image) -> float:
    """
    基于布局结构计算PPT相似度分数 (0-100)
    不依赖时间假设，只分析画面内容
    """
    if image is None:
        return 0.0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # 1. 文字密度（Otsu二值化后白色区域占比）
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    text_density = np.count_nonzero(binary) / (h * w)

    # 2. 结构化布局：上中下三区的文字密度分布
    top = binary[:h//3, :]
    mid = binary[h//3:2*h//3, :]
    bot = binary[2*h//3:, :]

    top_d = np.count_nonzero(top) / top.size
    mid_d = np.count_nonzero(mid) / mid.size
    bot_d = np.count_nonzero(bot) / bot.size

    # 3. 水平边缘密度（文字行产生水平边缘）
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    h_edges = np.count_nonzero(np.abs(sobelx) > 30) / (h * w)

    # 4. 垂直边缘密度
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    v_edges = np.count_nonzero(np.abs(sobely) > 30) / (h * w)

    # 5. 颜色对比度
    contrast = np.std(gray)

    # 6. 背景均匀性（PPT背景通常均匀）
    bg_uniformity = 1.0 - min(np.std(gray[:h//4, :]) / 128.0, 1.0)

    # ===== 评分逻辑 =====
    score = 0.0

    # 文字密度：PPT通常有5-60%的文字区域
    if 0.05 <= text_density <= 0.60:
        score += 20
    elif text_density < 0.05:
        score += text_density * 200
    else:
        score += 10

    # 结构化布局：PPT有标题区+内容区+留白
    if top_d > 0.03:
        score += 12
    if mid_d > 0.02:
        score += 8
    if bot_d < top_d * 0.5 and top_d > 0.02:
        score += 15  # 底部留白是强PPT特征

    # 水平边缘 > 垂直边缘（文字行特征）
    if h_edges > 0.003:
        score += 10
    if h_edges > v_edges * 1.0:
        score += 10

    # 对比度
    if contrast > 35:
        score += 15
    elif contrast > 20:
        score += 5

    # 背景均匀性
    if bg_uniformity > 0.7:
        score += 10

    return min(score, 100.0)


def detect_ppt_start(video_path: str, scan_duration: float = 60.0, 
                      sample_interval: float = 1.0,
                      score_threshold: float = 50.0) -> float:
    """
    检测PPT真正开始的时间点

    在视频前 scan_duration 秒内每秒采样，找到PPT分数首次超过阈值的位置
    返回: PPT开始时间（秒），如果未找到则返回 0.0
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0

    fps = cap.get(cv2.CAP_PROP_FPS)
    max_frames = int(scan_duration * fps)
    sample_step = int(sample_interval * fps)

    best_time = 0.0
    best_score = 0.0
    ppt_started = False

    for pos in range(0, max_frames, sample_step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret:
            break

        current_time = pos / fps
        score = compute_ppt_score(frame)

        # 找到第一个超过阈值的帧 = PPT开始
        if score >= score_threshold and not ppt_started:
            best_time = current_time
            best_score = score
            ppt_started = True
            break

        # 同时记录最高分（作为备选）
        if score > best_score:
            best_score = score
            best_time = current_time

    cap.release()

    print(f"[PPT定位] 扫描前{scan_duration:.0f}s, 阈值{score_threshold:.0f}")
    print(f"[PPT定位] PPT开始时间: {best_time:.1f}s (分数{best_score:.1f})")
    return best_time


class FrameExtractor:
    """视频关键帧提取器 — 基于布局分析的PPT智能定位"""

    def __init__(self, config: Dict):
        self.config = config.get("frame_extraction", {})
        self.method = self.config.get("method", "scene_change")
        self.scene_threshold = self.config.get("scene_threshold", 0.12)
        self.interval = self.config.get("interval", 25)
        self.min_interval = self.config.get("min_interval", 2)
        self.format = self.config.get("format", "jpg")
        self.max_width = self.config.get("max_width", 1280)

        # PPT定位配置
        self.ppt_scan_duration = self.config.get("ppt_scan_duration", 60.0)
        self.ppt_score_threshold = self.config.get("ppt_score_threshold", 50.0)
        self.ppt_min_score = self.config.get("ppt_min_score", 35.0)

    def extract_frames(self, video_path: str, output_dir: str) -> List[Dict]:
        """
        从视频中提取PPT关键帧
        步骤:
        1. 定位PPT真正开始的时间
        2. 从该时间点前后提取候选帧（场景变化+固定间隔）
        3. 用PPT分数过滤非PPT帧
        4. 直方图去重
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        temp_dir = output_path / ".temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir()

        # ========== 步骤1: 定位PPT真正开始的时间 ==========
        print(f"[帧提取] 步骤1: 定位PPT开始时间...")
        ppt_start_time = detect_ppt_start(
            video_path,
            scan_duration=self.ppt_scan_duration,
            score_threshold=self.ppt_score_threshold
        )

        # 如果PPT开始时间>0，我们只从该时间点前5秒开始提取（避免漏掉封面）
        extract_start = max(0, ppt_start_time - 5.0)
        print(f"[帧提取] 提取起始时间: {extract_start:.1f}s (PPT开始于 {ppt_start_time:.1f}s)")

        # ========== 步骤2: 场景变化检测 ==========
        print(f"[帧提取] 步骤2: ffmpeg场景变化检测 (threshold={self.scene_threshold})")

        # 从 extract_start 开始提取，避免片头干扰
        cmd1 = [
            "ffmpeg", "-y",
            "-ss", str(extract_start),
            "-i", video_path,
            "-vf", f"select=gt(scene\,{self.scene_threshold}),scale={self.max_width}:-1",
            "-vsync", "vfr",
            "-q:v", "2",
            str(temp_dir / "scene_%04d.jpg")
        ]
        subprocess.run(cmd1, capture_output=True, text=True, timeout=120)
        scene_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("scene_")])
        print(f"[帧提取] 步骤2: {len(scene_files)} 张场景变化帧")

        # ========== 步骤3: 固定间隔保底 ==========
        print(f"[帧提取] 步骤3: 每{self.interval}s强制提取")
        cmd2 = [
            "ffmpeg", "-y",
            "-ss", str(extract_start),
            "-i", video_path,
            "-vf", f"fps=1/{self.interval},scale={self.max_width}:-1",
            "-q:v", "2",
            str(temp_dir / "interval_%04d.jpg")
        ]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        interval_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("interval_")])
        print(f"[帧提取] 步骤3: {len(interval_files)} 张保底帧")

        # ========== 步骤4: 收集所有帧并计算PPT分数 ==========
        print(f"[帧提取] 步骤4: PPT布局分析...")

        frame_data = []
        for f in sorted(os.listdir(temp_dir)):
            if not f.endswith('.jpg'):
                continue
            path = str(temp_dir / f)
            img = cv2.imread(path)
            if img is None:
                continue

            # 时间戳（需要加上 extract_start 的偏移）
            if f.startswith("interval_"):
                idx = int(f.replace("interval_", "").replace(".jpg", ""))
                t = extract_start + (idx - 1) * self.interval
            else:
                idx = int(f.replace("scene_", "").replace(".jpg", ""))
                t = extract_start + idx * 8.0

            # 计算PPT分数
            ppt_score = compute_ppt_score(img)

            # 特征计算（用于去重）
            small = cv2.resize(img, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
            cv2.normalize(hist, hist)

            frame_data.append({
                "file": f, "path": path, "timestamp": t,
                "hist": hist, "gray": gray, "img": img,
                "ppt_score": ppt_score
            })

        frame_data.sort(key=lambda x: x["timestamp"])
        print(f"[帧提取] 共收集 {len(frame_data)} 帧")

        # ========== 步骤5: PPT分数过滤 ==========
        print(f"[帧提取] 步骤5: PPT分数过滤 (阈值{self.ppt_min_score})")

        ppt_frames = []
        for fd in frame_data:
            if fd["ppt_score"] >= self.ppt_min_score:
                ppt_frames.append(fd)
                print(f"  ✓ @{fd['timestamp']:6.1f}s | PPT分数{fd['ppt_score']:5.1f} | {fd['file']}")
            else:
                print(f"  ✗ @{fd['timestamp']:6.1f}s | PPT分数{fd['ppt_score']:5.1f} | {fd['file']} (过滤)")

        print(f"[帧提取] PPT过滤后: {len(ppt_frames)}/{len(frame_data)} 帧")

        # ========== 步骤6: 直方图去重 ==========
        print(f"[帧提取] 步骤6: 直方图去重")
        kept = []
        last_hist = None
        last_gray = None

        for fd in ppt_frames:
            if last_hist is None:
                keep = True
            else:
                sim = cv2.compareHist(fd["hist"], last_hist, cv2.HISTCMP_CORREL)
                pixel_diff = np.mean(np.abs(fd["gray"].astype(float) - last_gray.astype(float)))
                keep = (sim < 0.92) or (pixel_diff > 6.0)

            if keep:
                new_name = f"frame_{fd['timestamp']:08.3f}s.jpg"
                new_path = str(output_path / new_name)
                cv2.imwrite(new_path, fd["img"], [cv2.IMWRITE_JPEG_QUALITY, 92])
                kept.append({"timestamp": fd["timestamp"], "path": new_path, "ppt_score": fd["ppt_score"]})
                last_hist = fd["hist"]
                last_gray = fd["gray"]

        shutil.rmtree(temp_dir)

        print(f"[帧提取] ✓ 完成！共 {len(kept)} 帧")
        for k in kept[:10]:
            print(f"  @{k['timestamp']:7.1f}s | PPT分数{k['ppt_score']:5.1f} | {os.path.basename(k['path'])}")
        if len(kept) > 10:
            print(f"  ... 共 {len(kept)} 帧")

        return kept
