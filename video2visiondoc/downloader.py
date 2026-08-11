"""
downloader.py —— B 站视频下载（API 直连）

为什么不直接用 yt-dlp：
    B 站对数据中心 IP 有反爬策略（HTTP 412 Precondition Failed），
    yt-dlp 直接抓页面经常被拦。改为调用 B 站公开 API 反而稳定：
        1. x/web-interface/view   → 拿到 aid / cid / 标题 / 时长 / UP 主
        2. x/player/playurl       → 拿到 DASH 音视频流地址（未登录最高 480P，
                                    对 PPT 画面与语音识别完全够用）
        3. 带 UA + Referer 头下载 video.m4s / audio.m4s
        4. ffmpeg 合并为 mp4，并提取 16kHz 单声道 wav（Whisper 最优输入）

依赖：requests、ffmpeg（系统命令）。可选回退：yt-dlp。
"""

import json
import re
import subprocess
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class BiliDownloader:
    """B 站视频下载器（API 直连，无需 Cookie）"""

    def __init__(self, workdir: str):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    # ---------- 信息解析 ----------

    @staticmethod
    def parse_bvid(url_or_bvid: str) -> str:
        """从 URL 或 BV 号中解析 BV 号"""
        m = re.search(r"BV[0-9A-Za-z]{10}", url_or_bvid)
        if not m:
            raise ValueError(f"无法从输入中解析 BV 号: {url_or_bvid}")
        return m.group(0)

    def get_video_info(self, bvid: str) -> dict:
        """获取视频基本信息（标题、时长、cid、UP 主等）"""
        r = self.session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers={"Referer": "https://www.bilibili.com"},
            timeout=30,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取视频信息失败: {data.get('message')}")
        d = data["data"]
        return {
            "bvid": bvid,
            "aid": d["aid"],
            "cid": d["cid"],
            "title": d["title"],
            "duration": d["duration"],
            "owner": d["owner"]["name"],
            "desc": d.get("desc", ""),
        }

    def get_dash_urls(self, bvid: str, cid: int) -> tuple[str, str]:
        """
        获取 DASH 音视频流地址。
        优先选择 avc 编码（兼容性最好），音频取码率最高者。
        返回 (video_url, audio_url)。
        """
        r = self.session.get(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "qn": 64, "fnval": 4048},
            headers={"Referer": f"https://www.bilibili.com/video/{bvid}/"},
            timeout=30,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取播放地址失败: {data.get('message')}")
        dash = data["data"].get("dash")
        if not dash:
            raise RuntimeError("未返回 DASH 流（可能需要登录 Cookie）")

        videos = dash["video"]
        avc = [v for v in videos if v["codecs"].startswith("avc")] or videos
        video = max(avc, key=lambda v: v.get("bandwidth", 0))
        audio = max(dash["audio"], key=lambda a: a.get("bandwidth", 0))
        return video["baseUrl"], audio["baseUrl"]

    # ---------- 下载与转码 ----------

    def _download(self, url: str, out_path: Path, referer: str) -> None:
        """带 Referer 头下载流文件（B 站 CDN 强制校验 Referer）"""
        with self.session.get(
            url,
            headers={"Referer": referer},
            stream=True,
            timeout=300,
        ) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)

    @staticmethod
    def _ffmpeg(args: list) -> None:
        subprocess.run(["ffmpeg", "-y", *args],
                       check=True, capture_output=True)

    def download(self, url_or_bvid: str) -> dict:
        """
        完整下载流程。
        返回 dict:
            info        视频信息（含 bvid/title/duration/owner）
            video_path  合并后的 mp4
            audio_path  16kHz 单声道 wav（供语音识别）
        """
        bvid = self.parse_bvid(url_or_bvid)
        info = self.get_video_info(bvid)
        print(f"  标题: {info['title']}")
        print(f"  时长: {info['duration']}s  UP主: {info['owner']}")

        video_url, audio_url = self.get_dash_urls(bvid, info["cid"])
        video_m4s = self.workdir / "video.m4s"
        audio_m4s = self.workdir / "audio.m4s"
        referer = f"https://www.bilibili.com/video/{bvid}/"

        print("  下载视频流...")
        self._download(video_url, video_m4s, referer)
        print("  下载音频流...")
        self._download(audio_url, audio_m4s, referer)

        video_path = self.workdir / "merged.mp4"
        audio_path = self.workdir / "audio_16k.wav"

        print("  合并音视频...")
        self._ffmpeg(["-i", str(video_m4s), "-i", str(audio_m4s),
                      "-c", "copy", str(video_path)])
        print("  提取 16kHz 单声道音频...")
        self._ffmpeg(["-i", str(audio_m4s), "-vn",
                      "-ar", "16000", "-ac", "1", str(audio_path)])

        return {"info": info,
                "video_path": str(video_path),
                "audio_path": str(audio_path)}
