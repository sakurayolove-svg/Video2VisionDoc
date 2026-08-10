"""
视觉文档生成器
将翻译后的字幕与关键帧组合成视觉文档
支持: HTML, Markdown, PDF
"""
import os
import json
import base64
from pathlib import Path
from typing import Dict, List, Optional
from datetime import timedelta


class VisionDocGenerator:
    """视觉文档生成器"""

    def __init__(self, config: Dict):
        self.config = config.get("vision_doc", {})
        self.template = self.config.get("template", "academic")
        self.output_format = self.config.get("output_format", "html")
        self.include_timeline = self.config.get("include_timeline", True)
        self.include_frames = self.config.get("include_frames", True)
        self.theme_color = self.config.get("theme_color", "#3b82f6")
        self.font_family = self.config.get("font_family", "'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif")
        self.mathjax = self.config.get("mathjax", True)

    def generate(self,
                 translated_data: Dict,
                 frames: List[Dict],
                 video_info: Dict,
                 output_dir: str) -> str:
        """
        生成视觉文档
        返回: 输出文件路径
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 将帧与字幕对齐
        aligned = self._align_frames_with_segments(translated_data.get("segments", []), frames)

        if self.output_format == "html":
            return self._generate_html(aligned, video_info, output_path)
        elif self.output_format == "markdown":
            return self._generate_markdown(aligned, video_info, output_path)
        elif self.output_format == "pdf":
            return self._generate_pdf(aligned, video_info, output_path)
        else:
            raise ValueError(f"不支持的输出格式: {self.output_format}")

    def _align_frames_with_segments(self, segments: List[Dict], frames: List[Dict]) -> List[Dict]:
        """将关键帧与字幕片段按时间对齐"""
        if not frames:
            # 无帧时，按固定间隔分组
            return self._group_segments_by_interval(segments, interval=30)

        aligned = []
        for frame in frames:
            frame_time = frame.get("timestamp", 0)
            # 找到该帧附近的所有字幕
            nearby_segments = [
                seg for seg in segments
                if abs(seg.get("start", 0) - frame_time) < 60  # 60秒窗口
            ]

            # 合并这些字幕
            text_parts = []
            for seg in nearby_segments:
                if self.config.get("keep_original", True):
                    text_parts.append(seg.get("translated", seg.get("text", "")))
                else:
                    text_parts.append(seg.get("translated", ""))

            aligned.append({
                "timestamp": frame_time,
                "frame_path": frame.get("path", ""),
                "text": " ".join(text_parts),
                "segments": nearby_segments,
            })

        return aligned

    def _group_segments_by_interval(self, segments: List[Dict], interval: int = 30) -> List[Dict]:
        """按固定时间间隔分组字幕"""
        if not segments:
            return []

        groups = []
        current_group = []
        current_start = segments[0].get("start", 0)

        for seg in segments:
            if seg.get("start", 0) - current_start > interval:
                if current_group:
                    text = " ".join([s.get("translated", s.get("text", "")) for s in current_group])
                    groups.append({
                        "timestamp": current_start,
                        "frame_path": "",
                        "text": text,
                        "segments": current_group,
                    })
                current_group = [seg]
                current_start = seg.get("start", 0)
            else:
                current_group.append(seg)

        if current_group:
            text = " ".join([s.get("translated", s.get("text", "")) for s in current_group])
            groups.append({
                "timestamp": current_start,
                "frame_path": "",
                "text": text,
                "segments": current_group,
            })

        return groups

    def _generate_html(self, aligned: List[Dict], video_info: Dict, output_path: Path) -> str:
        """生成HTML视觉文档"""
        title = video_info.get("title", "视觉文档")
        author = video_info.get("owner", {}).get("name", "Unknown")
        bvid = video_info.get("bvid", "")

        # 读取帧图片为base64
        slides_html = []
        for i, item in enumerate(aligned, 1):
            timestamp = item.get("timestamp", 0)
            time_str = self._fmt_time(timestamp)
            text = item.get("text", "").strip()
            frame_path = item.get("frame_path", "")

            # 图片处理
            img_html = ""
            if frame_path and os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode()
                ext = Path(frame_path).suffix.lstrip(".")
                img_html = f'<img src="data:image/{ext};base64,{img_data}" alt="frame_{i}" style="max-width:100%;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.3);"/>'
            else:
                img_html = f'<div style="background:#1e293b;border:2px dashed #475569;border-radius:8px;padding:40px;text-align:center;color:#64748b;">[无画面] 时间戳 {time_str}</div>'

            slide_html = f"""
            <div class="slide-block" id="slide-{i}">
              <div class="timestamp">{time_str}</div>
              <div class="ppt-frame">
                <div class="slide-num">Slide {i}</div>
                {img_html}
              </div>
              <div class="transcript">
                <div class="label">中文讲解</div>
                <p>{self._escape_html(text)}</p>
              </div>
            </div>
            """
            slides_html.append(slide_html)

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self._escape_html(title)} — 视觉文档</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: {self.font_family};
    background: #0f172a;
    color: #e2e8f0;
    line-height: 1.7;
  }}
  .header {{
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    padding: 40px 20px;
    text-align: center;
    border-bottom: 2px solid #334155;
  }}
  .header h1 {{
    font-size: 1.9rem;
    color: #f8fafc;
    margin-bottom: 12px;
    letter-spacing: 0.5px;
  }}
  .header .meta {{
    color: #94a3b8;
    font-size: 0.95rem;
  }}
  .header .meta span {{ margin: 0 10px; }}
  .container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 30px 20px 60px;
  }}
  .slide-block {{
    display: flex;
    gap: 28px;
    margin-bottom: 50px;
    align-items: flex-start;
  }}
  .timestamp {{
    flex-shrink: 0;
    width: 70px;
    text-align: right;
    font-family: "Courier New", monospace;
    font-size: 0.9rem;
    color: {self.theme_color};
    font-weight: bold;
    padding-top: 12px;
  }}
  .ppt-frame {{
    flex-shrink: 0;
    width: 420px;
    min-height: 200px;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 20px;
    position: relative;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .ppt-frame .slide-num {{
    position: absolute;
    top: 10px;
    right: 14px;
    font-size: 0.75rem;
    color: #64748b;
  }}
  .transcript {{
    flex: 1;
    background: #1e293b;
    border-left: 4px solid {self.theme_color};
    border-radius: 0 10px 10px 0;
    padding: 22px 24px;
    font-size: 0.95rem;
    color: #e2e8f0;
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  }}
  .transcript .label {{
    font-size: 0.75rem;
    color: {self.theme_color};
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 10px;
    font-weight: bold;
  }}
  .transcript p {{ margin-bottom: 10px; }}
  .divider {{
    height: 1px;
    background: linear-gradient(90deg, transparent, #334155, transparent);
    margin: 40px 0;
  }}
  @media (max-width: 900px) {{
    .slide-block {{ flex-direction: column; }}
    .ppt-frame {{ width: 100%; }}
    .timestamp {{ text-align: left; width: auto; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>{self._escape_html(title)}</h1>
  <div class="meta">
    <span>UP主: {self._escape_html(author)}</span>
    <span>BV号: {bvid}</span>
  </div>
  <div class="meta" style="margin-top:8px; font-size:0.85rem;">
    由 Video2VisionDoc 自动生成
  </div>
</div>
<div class="container">
{chr(10).join(slides_html)}
<div class="divider"></div>
<div style="text-align:center; color:#64748b; font-size:0.85rem; padding: 20px;">
  <p>本视觉文档由 Video2VisionDoc 自动生成</p>
  <p>生成时间: 2026-08-10</p>
</div>
</div>
</body>
</html>"""

        output_file = output_path / f"{self._safe_name(title)}_vision_doc.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"[文档] HTML已生成: {output_file}")
        return str(output_file)

    def _generate_markdown(self, aligned: List[Dict], video_info: Dict, output_path: Path) -> str:
        """生成Markdown视觉文档"""
        title = video_info.get("title", "视觉文档")
        author = video_info.get("owner", {}).get("name", "Unknown")
        bvid = video_info.get("bvid", "")

        lines = [
            f"# {title}",
            "",
            f"> UP主: {author} | BV号: {bvid}",
            f"> 生成工具: Video2VisionDoc",
            "",
            "---",
            "",
        ]

        for i, item in enumerate(aligned, 1):
            timestamp = item.get("timestamp", 0)
            time_str = self._fmt_time(timestamp)
            text = item.get("text", "").strip()
            frame_path = item.get("frame_path", "")

            lines.append(f"## Slide {i} | {time_str}")
            lines.append("")
            if frame_path and os.path.exists(frame_path):
                rel_path = os.path.relpath(frame_path, output_path)
                lines.append(f"![frame_{i}]({rel_path})")
                lines.append("")
            lines.append(text)
            lines.append("")
            lines.append("---")
            lines.append("")

        md_content = "\n".join(lines)
        output_file = output_path / f"{self._safe_name(title)}_vision_doc.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"[文档] Markdown已生成: {output_file}")
        return str(output_file)

    def _generate_pdf(self, aligned: List[Dict], video_info: Dict, output_path: Path) -> str:
        """生成PDF（先生成HTML再转换）"""
        try:
            from weasyprint import HTML
        except ImportError:
            raise ImportError("PDF生成需要安装: pip install weasyprint")

        html_path = self._generate_html(aligned, video_info, output_path)
        pdf_path = output_path / f"{self._safe_name(video_info.get('title', 'doc'))}_vision_doc.pdf"

        HTML(filename=html_path).write_pdf(str(pdf_path))
        print(f"[文档] PDF已生成: {pdf_path}")
        return str(pdf_path)

    def _fmt_time(self, seconds: float) -> str:
        """格式化时间"""
        td = timedelta(seconds=int(seconds))
        return str(td)  # HH:MM:SS

    def _safe_name(self, name: str) -> str:
        """安全化文件名"""
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", name)[:50]

    def _escape_html(self, text: str) -> str:
        """HTML转义"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#x27;"))
