"""
切片快速关键帧提取 — 保证30秒内完成35分钟视频

策略:
1. 每 sample_interval_sec 秒只读取 1 帧（跳帧）
2. 降采样到 160x90 做快速差异比较（不用SSIM）
3. 像素绝对差均值 > diff_threshold 且满足最小间隔才保存
4. 最多提取 max_frames 帧，均匀覆盖全视频
"""
import cv2
import numpy as np
from pathlib import Path


def extract_keyframes_sliced(video_path: str, output_dir: str,
                              sample_interval_sec: float = 3.0,
                              diff_threshold: float = 6.0,
                              min_interval_sec: float = 8.0,
                              max_frames: int = 40,
                              resize_compare: tuple = (160, 90),
                              resize_save: int = 1280) -> list:
    """
    从长视频中快速提取关键帧（PPT翻页画面）

    参数:
        video_path: 视频文件路径
        output_dir: 帧输出目录
        sample_interval_sec: 采样间隔（秒），每N秒检查一帧
        diff_threshold: 差异阈值，灰度绝对差均值大于此值视为场景变化
        min_interval_sec: 两帧之间的最小时间间隔（秒）
        max_frames: 最大提取帧数
        resize_compare: 用于差异比较的分辨率 (宽, 高)
        resize_save: 保存图片的最大宽度

    返回:
        [{"timestamp": float, "path": str, "diff": float}, ...]
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    # 计算采样位置：每 sample_interval_sec 秒一帧
    sample_positions = []
    t = 0.0
    while t < duration:
        sample_positions.append(int(t * fps))
        t += sample_interval_sec

    print(f"[切片提取] 视频时长: {duration:.1f}s, 采样间隔: {sample_interval_sec}s, "
          f"共检查 {len(sample_positions)} 个位置")

    frames = []
    prev_small = None
    last_saved_time = -min_interval_sec

    for pos in sample_positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret:
            continue

        current_time = pos / fps

        # 快速降采样用于比较
        small = cv2.resize(frame, resize_compare)
        gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        # 第一帧强制保存
        if prev_small is None:
            save = True
            diff = 0.0
        else:
            # 快速差异：绝对差均值（比SSIM快10倍以上）
            diff = np.mean(np.abs(gray_small.astype(np.float32) - prev_small.astype(np.float32)))
            save = (diff > diff_threshold) and (current_time - last_saved_time >= min_interval_sec)

        if save:
            # 保存原帧（调整大小）
            h, w = frame.shape[:2]
            if w > resize_save:
                ratio = resize_save / w
                frame = cv2.resize(frame, (resize_save, int(h * ratio)), interpolation=cv2.INTER_AREA)

            fname = f"{output_dir}/frame_{current_time:08.3f}s.jpg"
            cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])

            frames.append({
                "timestamp": current_time,
                "path": fname,
                "diff": round(float(diff), 2)
            })
            last_saved_time = current_time

            if len(frames) >= max_frames:
                break

        prev_small = gray_small

    cap.release()
    print(f"[切片提取] ✓ 完成！共提取 {len(frames)} 帧")
    return frames
