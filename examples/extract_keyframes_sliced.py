"""
PPT画面完整提取器 — 两阶段策略

阶段1: ffmpeg 场景变化检测 (低阈值 0.15，捕获所有PPT翻页)
阶段2: 每30秒强制提取一帧 (保底，防止遗漏)
阶段3: 直方图去重 (合并两阶段结果，去掉重复帧)

特点:
- 不需要定时提取关键帧
- 帧间隔可以很长(几分钟)
- 但PPT翻页一定会被捕获
- 适当多提取(通常40-60帧覆盖35分钟)
"""
import cv2
import numpy as np
import subprocess
import os
import shutil
from pathlib import Path


def extract_keyframes_ppt_complete(video_path: str, output_dir: str,
                                    scene_threshold: float = 0.15,
                                    interval_sec: float = 30.0,
                                    hist_sim_threshold: float = 0.90,
                                    resize_save: int = 1280) -> list:
    """
    完整PPT画面提取 — 两阶段策略确保不遗漏任何PPT

    参数:
        video_path: 视频文件路径
        output_dir: 帧输出目录
        scene_threshold: ffmpeg场景变化阈值 (0~1, 越低越敏感)
        interval_sec: 保底固定间隔 (秒)
        hist_sim_threshold: 直方图去重阈值 (高于此值认为是同一PPT)
        resize_save: 保存图片的最大宽度

    返回:
        [{"timestamp": float, "path": str}, ...]
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    temp_dir = f"{output_dir}/.temp"
    Path(temp_dir).mkdir(parents=True, exist_ok=True)

    # ========== 阶段1: 场景变化检测 ==========
    print(f"[PPT提取] 阶段1: ffmpeg场景变化检测 (threshold={scene_threshold})")
    cmd1 = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"select=gt(scene\,{scene_threshold}),scale={resize_save}:-1",
        "-vsync", "vfr",
        "-q:v", "2",
        f"{temp_dir}/scene_%04d.jpg"
    ]
    r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=120)
    scene_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("scene_")])
    print(f"[PPT提取] 阶段1完成: {len(scene_files)} 张场景变化帧")

    # ========== 阶段2: 固定间隔保底 ==========
    print(f"[PPT提取] 阶段2: 每{interval_sec}s强制提取")
    cmd2 = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval_sec},scale={resize_save}:-1",
        "-q:v", "2",
        f"{temp_dir}/interval_%04d.jpg"
    ]
    r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
    interval_files = sorted([f for f in os.listdir(temp_dir) if f.startswith("interval_")])
    print(f"[PPT提取] 阶段2完成: {len(interval_files)} 张保底帧")

    # ========== 阶段3: 直方图去重 ==========
    print(f"[PPT提取] 阶段3: 直方图去重 (threshold={hist_sim_threshold})")

    # 收集所有帧并计算特征
    frame_data = []
    for f in sorted(os.listdir(temp_dir)):
        if not f.endswith('.jpg'):
            continue
        path = os.path.join(temp_dir, f)
        img = cv2.imread(path)
        if img is None:
            continue

        # 获取时间戳
        if f.startswith("interval_"):
            idx = int(f.replace("interval_", "").replace(".jpg", ""))
            t = (idx - 1) * interval_sec
        else:
            # scene帧: 从文件序号粗略估计
            idx = int(f.replace("scene_", "").replace(".jpg", ""))
            t = idx * 10.0

        # 计算直方图特征
        small = cv2.resize(img, (320, 180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)

        frame_data.append({"file": f, "path": path, "timestamp": t, "hist": hist, "gray": gray})

    # 按时间排序
    frame_data.sort(key=lambda x: x["timestamp"])

    # 去重保留
    kept = []
    last_hist = None
    last_gray = None

    for fd in frame_data:
        if last_hist is None:
            keep = True
        else:
            sim = cv2.compareHist(fd["hist"], last_hist, cv2.HISTCMP_CORREL)
            pixel_diff = np.mean(np.abs(fd["gray"].astype(float) - last_gray.astype(float)))
            # 直方图相似度<0.90 或 像素差异>8 才保留
            keep = (sim < hist_sim_threshold) or (pixel_diff > 8.0)

        if keep:
            # 重命名为统一格式
            new_name = f"frame_{fd['timestamp']:08.3f}s.jpg"
            new_path = os.path.join(output_dir, new_name)
            shutil.copy2(fd["path"], new_path)
            kept.append({"timestamp": fd["timestamp"], "path": new_path})
            last_hist = fd["hist"]
            last_gray = fd["gray"]

    # 清理临时文件
    shutil.rmtree(temp_dir)

    print(f"[PPT提取] ✓ 完成！共 {len(kept)} 帧 (去重前 {len(frame_data)} 帧)")
    for k in kept:
        print(f"  @{k['timestamp']:7.1f}s | {os.path.basename(k['path'])}")

    return kept
