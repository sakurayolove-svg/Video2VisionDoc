"""
【经典三方法抽帧：scene_change / fixed_interval / ocr_trigger（与 interval_dhash、ppt_layout 同级）】
本文件复制自初版提交（77b7995）中的 src/extractors/frame_extractor.py，
纳入 video2visiondoc 框架作为同级可切换模块。
注意：当前 src/ 下的同名文件已演进为 PPT 布局分析版（见 keyframes_ppt_layout.py），
本文件对应的是最初版实现，原始提交保留于 git 历史未作修改。
"""
import os
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from skimage.metrics import structural_similarity as ssim


class FrameExtractor:
    """视频关键帧提取器"""

    def __init__(self, config: Dict):
        self.config = config.get("frame_extraction", {})
        self.method = self.config.get("method", "scene_change")
        self.scene_threshold = self.config.get("scene_threshold", 0.3)
        self.interval = self.config.get("interval", 5)
        self.min_interval = self.config.get("min_interval", 2)
        self.format = self.config.get("format", "jpg")
        self.max_width = self.config.get("max_width", 1280)
        self.ocr_enabled = self.config.get("ocr_enabled", False)

    def extract_frames(self, video_path: str, output_dir: str) -> List[Dict]:
        """
        从视频中提取关键帧
        返回: [
            {"timestamp": float, "path": str, "method": str},
            ...
        ]
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        print(f"[帧提取] 视频信息: {total_frames}帧, {fps:.2f}fps, 时长{duration:.1f}s")

        if self.method == "scene_change":
            frames = self._extract_by_scene_change(cap, fps, output_path)
        elif self.method == "fixed_interval":
            frames = self._extract_by_interval(cap, fps, output_path)
        elif self.method == "ocr_trigger":
            frames = self._extract_by_ocr(cap, fps, output_path)
        else:
            raise ValueError(f"不支持的提取方法: {self.method}")

        cap.release()
        print(f"[帧提取] 共提取 {len(frames)} 帧")
        return frames

    def _extract_by_scene_change(self, cap, fps: float, output_path: Path) -> List[Dict]:
        """基于场景变化检测提取关键帧"""
        frames = []
        prev_frame = None
        frame_idx = 0
        last_saved_time = -self.min_interval

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            current_time = frame_idx / fps
            frame_idx += 1

            # 转换为灰度图
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (320, 180))  # 降采样加速

            if prev_frame is not None:
                # 计算结构相似度
                score = ssim(prev_frame, gray, data_range=255)
                diff = 1 - score  # 差异度

                if diff > self.scene_threshold and (current_time - last_saved_time) >= self.min_interval:
                    frame_path = self._save_frame(frame, output_path, current_time)
                    frames.append({
                        "timestamp": current_time,
                        "path": str(frame_path),
                        "method": "scene_change",
                        "diff_score": float(diff),
                    })
                    last_saved_time = current_time

            prev_frame = gray

        # 确保至少提取第一帧和最后一帧
        if not frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            if ret:
                frame_path = self._save_frame(frame, output_path, 0)
                frames.append({"timestamp": 0, "path": str(frame_path), "method": "fallback"})

        return frames

    def _extract_by_interval(self, cap, fps: float, output_path: Path) -> List[Dict]:
        """按固定间隔提取帧"""
        frames = []
        interval_frames = int(self.interval * fps)
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % interval_frames == 0:
                current_time = frame_idx / fps
                frame_path = self._save_frame(frame, output_path, current_time)
                frames.append({
                    "timestamp": current_time,
                    "path": str(frame_path),
                    "method": "fixed_interval",
                })

            frame_idx += 1

        return frames

    def _extract_by_ocr(self, cap, fps: float, output_path: Path) -> List[Dict]:
        """基于OCR文字变化触发提取（需要pytesseract）"""
        try:
            import pytesseract
        except ImportError:
            raise ImportError("OCR模式需要安装: pip install pytesseract")

        frames = []
        prev_text = ""
        frame_idx = 0
        last_saved_time = -self.min_interval

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            current_time = frame_idx / fps
            frame_idx += 1

            # 每5秒检测一次OCR
            if frame_idx % int(5 * fps) == 0:
                text = pytesseract.image_to_string(frame, lang="eng+chi_sim")

                # 如果文字内容变化显著
                if self._text_diff(prev_text, text) > 0.3 and (current_time - last_saved_time) >= self.min_interval:
                    frame_path = self._save_frame(frame, output_path, current_time)
                    frames.append({
                        "timestamp": current_time,
                        "path": str(frame_path),
                        "method": "ocr_trigger",
                    })
                    last_saved_time = current_time
                    prev_text = text

        return frames

    def _save_frame(self, frame: np.ndarray, output_path: Path, timestamp: float) -> Path:
        """保存单帧"""
        # 调整大小
        h, w = frame.shape[:2]
        if w > self.max_width:
            ratio = self.max_width / w
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            frame = cv2.resize(frame, (new_w, new_h))

        filename = f"frame_{timestamp:06.2f}s.{self.format}"
        filepath = output_path / filename

        if self.format == "jpg":
            cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        else:
            cv2.imwrite(str(filepath), frame)

        return filepath

    def _text_diff(self, text1: str, text2: str) -> float:
        """计算两段文本的差异度"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 and not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return 1 - len(intersection) / len(union) if union else 0.0
