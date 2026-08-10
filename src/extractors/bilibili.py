"""
B站视频下载器
支持: 普通视频、番剧、课程、合集
"""
import os
import re
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
import requests


class BiliVideoExtractor:
    """B站视频提取器"""

    def __init__(self, config: Dict):
        self.config = config.get("bilibili", {})
        self.quality = self.config.get("quality", 80)
        self.timeout = self.config.get("timeout", 120)
        self.threads = self.config.get("threads", 4)
        self.cookie_file = self.config.get("cookie_file", "")
        self.temp_dir = Path(tempfile.gettempdir()) / "v2vd_bili"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def parse_bvid(self, url: str) -> Optional[str]:
        """从URL中提取BV号"""
        # 支持格式:
        # https://www.bilibili.com/video/BV13T3x69Eqz
        # https://b23.tv/BV13T3x69Eqz
        # BV13T3x69Eqz
        patterns = [
            r'BV[0-9A-Za-z]{10}',
            r'bilibili\.com/video/(BV[0-9A-Za-z]{10})',
            r'b23\.tv/(BV[0-9A-Za-z]{10})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1) if match.groups() else match.group(0)
        return None

    def get_video_info(self, bvid: str) -> Dict:
        """通过B站API获取视频信息"""
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }
        resp = requests.get(api_url, headers=headers, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取视频信息失败: {data.get('message')}")
        return data["data"]

    def get_subtitle(self, bvid: str, cid: int) -> Optional[List[Dict]]:
        """获取视频字幕(人工/AI字幕)"""
        api_url = f"https://api.bilibili.com/x/player/wbi/v2?cid={cid}&bvid={bvid}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://www.bilibili.com/video/{bvid}/",
        }
        resp = requests.get(api_url, headers=headers, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            return None

        subtitle_data = data.get("data", {}).get("subtitle", {})
        subtitles = subtitle_data.get("subtitles", [])

        if not subtitles:
            return None

        # 下载字幕内容
        result = []
        for sub in subtitles:
            sub_url = sub.get("subtitle_url", "")
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            try:
                sub_resp = requests.get(sub_url, headers=headers, timeout=30)
                sub_content = sub_resp.json()
                result.append({
                    "lan": sub.get("lan", ""),
                    "lan_doc": sub.get("lan_doc", ""),
                    "content": sub_content,
                })
            except Exception:
                continue
        return result if result else None

    def download_video(self, url: str, output_dir: str) -> Dict:
        """
        下载B站视频
        返回: {
            "video_path": str,
            "audio_path": str,
            "info": dict,
            "subtitles": list or None,
            "title": str,
            "bvid": str,
        }
        """
        bvid = self.parse_bvid(url)
        if not bvid:
            raise ValueError(f"无法从URL解析BV号: {url}")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 获取视频信息
        info = self.get_video_info(bvid)
        title = info.get("title", bvid)
        cid = info.get("cid")
        duration = info.get("duration", 0)

        # 安全化文件名
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
        base_name = f"{safe_title}_{bvid}"

        # 尝试获取字幕
        subtitles = self.get_subtitle(bvid, cid) if cid else None

        # 使用 yt-dlp 下载
        video_file = output_path / f"{base_name}.mp4"
        audio_file = output_path / f"{base_name}.wav"

        # 构建 yt-dlp 命令
        ydl_opts = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            f"--output", str(output_path / f"{base_name}.%(ext)s"),
            f"--format", f"bestvideo[height<={self.quality}p]+bestaudio/best",
            "--merge-output-format", "mp4",
            "--retries", "3",
            "--fragment-retries", "3",
            "--concurrent-fragments", str(self.threads),
        ]

        if self.cookie_file and os.path.exists(self.cookie_file):
            ydl_opts.extend(["--cookies", self.cookie_file])

        ydl_opts.append(f"https://www.bilibili.com/video/{bvid}/")

        print(f"[下载] 开始下载: {title}")
        print(f"[下载] 命令: {' '.join(ydl_opts)}")

        result = subprocess.run(
            ydl_opts,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

        if result.returncode != 0:
            print(f"[警告] yt-dlp stderr: {result.stderr}")

        # 检查下载结果
        downloaded_files = list(output_path.glob(f"{base_name}.*"))
        video_path = None
        for f in downloaded_files:
            if f.suffix in [".mp4", ".mkv", ".flv"]:
                video_path = f
                break

        if not video_path or not video_path.exists():
            raise FileNotFoundError(f"视频下载失败，未找到输出文件: {output_path / base_name}.*")

        print(f"[下载] 视频已保存: {video_path}")

        # 提取音频
        if not audio_file.exists():
            self._extract_audio(str(video_path), str(audio_file))

        return {
            "video_path": str(video_path),
            "audio_path": str(audio_file),
            "info": info,
            "subtitles": subtitles,
            "title": title,
            "bvid": bvid,
            "duration": duration,
            "cid": cid,
        }

    def _extract_audio(self, video_path: str, audio_path: str):
        """使用ffmpeg从视频中提取音频"""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",  # 无视频
            "-acodec", "pcm_s16le",  # 16bit PCM
            "-ar", "16000",  # 16kHz
            "-ac", "1",  # 单声道
            audio_path,
        ]
        print(f"[音频] 提取音频: {audio_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg提取音频失败: {result.stderr}")
        print(f"[音频] 音频已保存: {audio_path}")


if __name__ == "__main__":
    import yaml
    with open("../../config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    extractor = BiliVideoExtractor(cfg)
    # test
    # result = extractor.download_video("BV13T3x69Eqz", "./test_output")
    # print(result)
