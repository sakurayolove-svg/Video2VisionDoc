"""
关键帧/PPT画面提取器 — 支持VLM PPT检测

两阶段提取 + VLM过滤:
1. ffmpeg场景变化检测(低阈值) + 固定间隔保底
2. VLM判断每帧是否为PPT，过滤掉演讲者/过渡/黑屏
3. 直方图去重

VLM优势:
- 准确识别封面/标题页(大字体、边缘少)
- 区分PPT幻灯片 vs 演讲者画面
- 不受阈值参数影响
"""
import cv2
import numpy as np
import subprocess
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional

# 尝试导入VLM检测器
try:
    from .vlm_ppt_detector import VLMPPTDetector
    HAS_VLM = True
except ImportError:
    HAS_VLM = False


class FrameExtractor:
    """视频关键帧提取器 — 支持VLM PPT检测"""

    def __init__(self, config: Dict):
        self.config = config.get("frame_extraction", {})
        self.method = self.config.get("method", "scene_change")
        self.scene_threshold = self.config.get("scene_threshold", 0.12)
        self.interval = self.config.get("interval", 25)
        self.min_interval = self.config.get("min_interval", 2)
        self.format = self.config.get("format", "jpg")
        self.max_width = self.config.get("max_width", 1280)
        self.ocr_enabled = self.config.get("ocr_enabled", False)

        # VLM配置
        self.use_vlm = self.config.get("use_vlm", False)
        self.vlm_model = self.config.get("vlm_model", "qwen-vl-chat")
        self.vlm_api_key = self.config.get("vlm_api_key", "")
        self._vlm_detector = None

    def _get_vlm_detector(self):
        if self._vlm_detector is None and HAS_VLM and self.use_vlm:
            self._vlm_detector = VLMPPTDetector(
                model=self.vlm_model,
                api_key=self.vlm_api_key
            )
        return self._vlm_detector

    def extract_frames(self, video_path: str, output_dir: str) -> List[Dict]:
        """
        从视频中提取PPT关键帧
        返回: [{"timestamp": float, "path": str, "is_ppt": bool}, ...]
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        temp_dir = output_path / ".temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir()

        # ========== 阶段1: 场景变化检测 ==========
        print(f"[帧提取] 阶段1: ffmpeg场景变化检测 (threshold={self.scene_threshold})")
        cmd1 = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"select=gt(scene\,{self.scene_threshold}),scale={self.max_width}:-1",
            "-vsync", "vfr",
            "-q:v", "2",
            str(temp_dir / "scene_%04d.jpg")
        ]
        subprocess.run(cmd1, capture_output=True, text=True, timeout=120)
        scene_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("scene_")])
        print(f"[帧提取] 阶段1: {len(scene_files)} 张场景变化帧")

        # ========== 阶段2: 固定间隔保底 ==========
        print(f"[帧提取] 阶段2: 每{self.interval}s强制提取")
        cmd2 = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"fps=1/{self.interval},scale={self.max_width}:-1",
            "-q:v", "2",
            str(temp_dir / "interval_%04d.jpg")
        ]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        interval_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("interval_")])
        print(f"[帧提取] 阶段2: {len(interval_files)} 张保底帧")

        # ========== 阶段3: 收集所有帧 ==========
        frame_data = []
        for f in sorted(os.listdir(temp_dir)):
            if not f.endswith('.jpg'):
                continue
            path = str(temp_dir / f)
            img = cv2.imread(path)
            if img is None:
                continue

            # 时间戳
            if f.startswith("interval_"):
                idx = int(f.replace("interval_", "").replace(".jpg", ""))
                t = (idx - 1) * self.interval
            else:
                idx = int(f.replace("scene_", "").replace(".jpg", ""))
                t = idx * 8.0

            # 特征计算
            small = cv2.resize(img, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
            cv2.normalize(hist, hist)

            frame_data.append({
                "file": f, "path": path, "timestamp": t,
                "hist": hist, "gray": gray,
                "img": img
            })

        frame_data.sort(key=lambda x: x["timestamp"])
        print(f"[帧提取] 共收集 {len(frame_data)} 帧")

        # ========== 阶段4: VLM PPT检测 (可选) ==========
        if self.use_vlm and HAS_VLM:
            print(f"[帧提取] 阶段4: VLM PPT检测 ({self.vlm_model})")
            detector = self._get_vlm_detector()
            if detector:
                ppt_frames = detector.filter_ppt_frames([
                    {"timestamp": fd["timestamp"], "path": fd["path"]} for fd in frame_data
                ])
                # 保留PPT帧的数据
                ppt_paths = {f["path"] for f in ppt_frames}
                frame_data = [fd for fd in frame_data if fd["path"] in ppt_paths]
                print(f"[帧提取] VLM过滤后: {len(frame_data)} 帧")
        else:
            # 启发式PPT判断 (封面保护)
            print(f"[帧提取] 阶段4: 启发式PPT检测 (封面保护)")
            filtered = []
            for fd in frame_data:
                gray = fd["gray"]
                _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                text_ratio = np.count_nonzero(binary) / binary.size
                edges = cv2.Canny(gray, 50, 150)
                edge_ratio = np.count_nonzero(edges) / edges.size
                brightness_std = np.std(gray)

                # 封面保护: 前20秒强制保留
                # 内容判断: 文字>3% 或 边缘>0.2% 且 有内容
                is_ppt = (text_ratio > 0.03 or edge_ratio > 0.002) and brightness_std > 12
                if fd["timestamp"] < 20.0:
                    is_ppt = True  # 前20秒强制保留（确保封面）

                if is_ppt:
                    filtered.append(fd)

            frame_data = filtered
            print(f"[帧提取] 启发式过滤后: {len(frame_data)} 帧")

        # ========== 阶段5: 直方图去重 ==========
        print(f"[帧提取] 阶段5: 直方图去重")
        kept = []
        last_hist = None
        last_gray = None

        for fd in frame_data:
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
                kept.append({"timestamp": fd["timestamp"], "path": new_path})
                last_hist = fd["hist"]
                last_gray = fd["gray"]

        shutil.rmtree(temp_dir)

        print(f"[帧提取] ✓ 完成！共 {len(kept)} 帧")
        for k in kept[:10]:
            print(f"  @{k['timestamp']:7.1f}s | {os.path.basename(k['path'])}")
        if len(kept) > 10:
            print(f"  ... 共 {len(kept)} 帧")

        return kept
