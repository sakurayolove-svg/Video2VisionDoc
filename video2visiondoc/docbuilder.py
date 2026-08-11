"""
docbuilder.py —— 视觉文档生成

输出两种形态：
    1. 自包含 HTML（默认）：所有 PPT 图片内嵌为 base64 Data URI，
       单文件即可离线浏览、邮件发送、网盘分享；
    2. PDF（可选）：检测到外部分页工具（Paged.js + Playwright，
       或 weasyprint）时可用，未安装时提示并保留 HTML。

页面结构（每页一节）：
    页眉：第 N 页 · 时间段
    主体：PPT 截图 + 中文译稿（无翻译时为英文原文）

依赖：标准库 + Pillow（可选，仅用于压缩内嵌图片）。
"""

import base64
import html as html_mod
import shutil
import subprocess
from pathlib import Path


def _fmt_time(seconds) -> str:
    if seconds is None:
        return "结束"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _img_data_uri(path: str, max_width: int = 852) -> str:
    """图片转 base64 Data URI（过大则先压缩，控制 HTML 体积）"""
    p = Path(path)
    try:
        from PIL import Image
        import io
        im = Image.open(p)
        if im.width > max_width:
            im = im.resize((max_width, int(im.height * max_width / im.width)))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        data = buf.getvalue()
    except ImportError:
        data = p.read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


CSS = """
body { font-family: "Noto Serif SC","Songti SC","PingFang SC",serif;
       color:#333; max-width: 900px; margin: 0 auto; padding: 2em;
       line-height: 1.7; }
h1 { font-size: 22pt; }
.meta { color:#666; font-size: 10pt; border-bottom: 2px solid #333;
        padding-bottom: 1em; margin-bottom: 2em; }
.slide { margin-bottom: 3em; page-break-before: always; }
.slide-head { border-bottom: 2px solid #333; padding-bottom: .3em;
              margin-bottom: .8em; }
.slide-head h2 { display:inline; font-size: 14pt; margin:0; }
.time { float:right; font-size: 9.5pt; color:#666; padding-top:.4em; }
figure { margin: .5em 0 1em 0; text-align:center; }
figure img { max-width: 100%; border: 1px solid #ccc; }
figcaption { font-size: 9pt; color:#666; margin-top:.3em; }
.trans p { margin: .6em 0; text-align: justify; }
"""


class VisionDocBuilder:
    """视觉文档构建器"""

    def build_html(self, blocks: list, video_info: dict,
                   out_path: str, doc_title: str = None) -> str:
        """
        生成自包含 HTML 视觉文档。
        blocks:     aligner+translator 处理后的页块列表
        video_info: downloader 返回的视频信息 dict
        返回输出文件路径。
        """
        title = doc_title or f"{video_info.get('title', '演讲视频')}——视觉文档"
        parts = [
            "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>",
            f"<title>{html_mod.escape(title)}</title>",
            f"<style>{CSS}</style></head><body>",
            f"<h1>{html_mod.escape(title)}</h1>",
            "<div class='meta'>",
            f"原视频：bilibili {video_info.get('bvid', '')}"
            f"（UP 主：{html_mod.escape(video_info.get('owner', ''))}）<br>",
            f"视频时长：约 {int(video_info.get('duration', 0)) // 60} 分钟 · "
            f"本文档由语音识别转写 + 翻译 + PPT 关键帧自动整理",
            "</div>",
        ]
        for b in blocks:
            t_range = f"{_fmt_time(b['t_start'])} – {_fmt_time(b['t_end'])}"
            zh = b.get("text_zh") or b.get("text", "")
            paras = "".join(
                f"<p>{html_mod.escape(p)}</p>"
                for p in zh.split("\n") if p.strip())
            parts += [
                "<div class='slide'>",
                f"<div class='slide-head'><h2>第 {b['index']} 页</h2>"
                f"<span class='time'>视频 {t_range}</span></div>",
                f"<figure><img src='{_img_data_uri(b['image'])}'>"
                f"<figcaption>幻灯片 {b['index']}</figcaption></figure>",
                f"<div class='trans'>{paras}</div>",
                "</div>",
            ]
        parts.append("</body></html>")

        Path(out_path).write_text("".join(parts), encoding="utf-8")
        print(f"  HTML 视觉文档: {out_path}")
        return out_path

    def build_pdf(self, html_path: str, pdf_path: str) -> str:
        """
        将 HTML 渲染为 PDF。
        优先使用 Playwright（打印为 PDF），未安装则尝试 weasyprint，
        都不可用时提示并返回 None。
        """
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(Path(html_path).as_uri())
                page.pdf(path=pdf_path, format="A4",
                         margin={"top": "2cm", "bottom": "2cm",
                                 "left": "1.8cm", "right": "1.8cm"})
                browser.close()
            print(f"  PDF 视觉文档: {pdf_path}")
            return pdf_path
        except ImportError:
            pass
        if shutil.which("weasyprint"):
            subprocess.run(["weasyprint", html_path, pdf_path], check=True)
            print(f"  PDF 视觉文档: {pdf_path}")
            return pdf_path
        print("  未安装 Playwright / WeasyPrint，跳过 PDF（HTML 已生成）")
        return None
