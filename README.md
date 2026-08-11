# Video2VisionDoc

**作者**: [sakurayolove-svg](https://github.com/sakurayolove-svg)  
**许可证**: BSD-3-Clause

将 B 站学术/演讲/课程视频一键转换为带时间轴、带 PPT 画面的视觉文档。

> **仓库结构说明（2026-08 更新）**
>
> 本仓库现有两套实现，均予保留：
>
> | 结构 | 位置 | 定位 |
> |------|------|------|
> | **推荐流水线（v2）** | `video2visiondoc/` 包 | 在真实任务中完整验证过的新结构，**推荐使用** |
> | 初版实现（v1） | `main.py` + `src/` + `config.yaml` | 早期版本，作为**补充**保留，接口更灵活（多引擎/多模板） |
>
> 下文“第〇节”介绍推荐流水线；第一节起的内容为初版实现的文档。

---

## 〇、推荐流水线（video2visiondoc/，v2）

`video2visiondoc/` 是在真实任务中验证过的实现——处理对象：BV13T3x69Eqz
（35 分钟英文演讲、**无任何字幕**、运行环境仅 4GB 内存 / 2 核 CPU / 无 GPU）。
实战中踩过的坑和对应的工程设计：

| 环节 | 实战经验 | 对应设计 |
|------|----------|----------|
| 下载 | yt-dlp 直连被 B 站反爬拦截（HTTP 412） | 改用 B 站公开 API：`view` 取 cid → `playurl` 取 DASH 流，带 UA+Referer 下载（`downloader.py`） |
| 转写 | medium/small 模型整段转写 35 分钟音频均被 OOM 杀掉 | **5 分钟分块转写** + VAD 过滤 + int8 量化，每块完成即落盘可断点续跑（`transcriber.py`） |
| 关键帧 | 纯场景变化检测阈值难调，漏静态页、混入演讲者镜头 | **每 10 秒均匀抽帧 + dHash 感知哈希去重**（256 bit，阈值 40），210 帧 → 27 帧（`keyframes.py`） |
| 对齐 | 60 秒滑窗配对上下文割裂 | **以每页 PPT 停留时间窗归组转写段**，一页一块（`aligner.py`） |
| 翻译 | 逐句翻译术语不一致 | **按页翻译**，OpenAI 兼容 API（`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`），无 Key 时优雅降级保留原文（`translator.py`） |
| 文档 | — | 自包含 HTML（图片 base64 内嵌，单文件离线分享），可选 PDF（`docbuilder.py`） |

### 快速开始

```bash
pip install -r requirements.txt   # 推荐流水线的最小依赖在文件顶部
# 系统需安装 ffmpeg

# 配置翻译（可选；不配置则保留英文原文）
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.openai.com/v1"   # 任意 OpenAI 兼容端点
export LLM_MODEL="gpt-4o-mini"

# 一键全流程
python -m video2visiondoc BV13T3x69Eqz -o ./output

# 改善专有名词识别：传入领域提示词
python -m video2visiondoc BV13T3x69Eqz \
    --prompt "Talk on sparse rewards in reinforcement learning, topology"

# 剔除演讲者镜头帧（第 2、3 帧，1 起计数）并输出 PDF
python -m video2visiondoc BV13T3x69Eqz --exclude-frames 2 3 --pdf
```

### 模块结构

```
video2visiondoc/
├── cli.py           # 六阶段编排：python -m video2visiondoc
├── downloader.py    # B 站 API 直连下载 → mp4 + 16kHz 单声道 wav
├── transcriber.py   # faster-whisper 分块转写（防 OOM，断点续跑）
├── keyframes.py     # 均匀抽帧 + dHash 去重 → slide_XX.jpg
├── aligner.py       # 按 PPT 页时间窗归组转写段
├── translator.py    # 按页翻译（OpenAI 兼容 API，术语保护）
└── docbuilder.py    # 自包含 HTML（+ 可选 PDF）
```

低内存环境提示：4GB 内存请使用 `--model small` 或更小；
模型下载慢可设 `HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1`。

---

## 一、基本信息（初版实现 v1）

Video2VisionDoc 是一个面向学术视频处理的自动化工具链，核心目标是将 Bilibili 上的演讲、课程、学术报告等长视频，自动提取语音文本、翻译为中文、捕获关键帧（PPT 画面），最终组合成一份可离线浏览、可分享、可检索的视觉文档。

典型应用场景：
- 国际学术会议/讲座的语音内容转录与中文可视化整理
- 在线课程的知识要点结构化归档
- 技术分享视频的快速概览与检索

---

## 二、使用流程

### 阶段 1：环境准备（输入）

**输入**：你的本地机器（Linux/macOS/Windows）

```bash
# 1. 克隆仓库
git clone https://github.com/sakurayolove-svg/Video2VisionDoc.git
cd Video2VisionDoc

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装系统依赖 ffmpeg
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
# Windows: 下载 https://ffmpeg.org/download.html 并加入 PATH
```

**输出**：`venv/` 虚拟环境就绪，所有 Python 包安装完成。

---

### 阶段 2：配置（输入）

**输入**：`config.yaml`（根据你的环境和需求修改）

关键配置项说明：

```yaml
# 语音转录引擎选择
transcription:
  engine: "faster-whisper"   # 选项: faster-whisper / whisper / openai-api
  model: "large-v3"          # 选项: tiny / base / small / medium / large-v3
  device: "cuda"             # cuda 或 cpu

# 翻译引擎选择
translation:
  engine: "openai"             # 选项: openai / deep-translator / argos
  target_language: "zh-CN"
  openai:
    api_key: ""                # 建议从环境变量 OPENAI_API_KEY 读取

# 关键帧提取策略
frame_extraction:
  method: "scene_change"       # 选项: scene_change / fixed_interval / ocr_trigger
  scene_threshold: 0.3       # 场景变化敏感度（0~1，越大越敏感）

# 视觉文档输出
vision_doc:
  output_format: "html"        # 选项: html / markdown / pdf
  template: "academic"         # 选项: default / academic / minimal
```

**输出**：一份针对你本地环境调优的 `config.yaml`。

---

### 阶段 3：执行处理（输入 → 中间产物）

**输入**：B 站视频 URL 或 BV 号

```bash
# 全自动模式（下载 → 转录 → 翻译 → 生成文档）
python main.py --url BV13T3x69Eqz

# 完整参数模式
python main.py \
  --url "https://www.bilibili.com/video/BV13T3x69Eqz" \
  --output ./output \
  --engine faster-whisper \
  --model large-v3 \
  --target-lang zh-CN \
  --format html
```

**中间产物**（输出到 `./output/temp/`）：
- `*.mp4` —— 下载的原始视频
- `*.wav` —— 提取的 16kHz 单声道音频
- `*_transcript.json` —— 带时间戳的语音转录结果
- `translated_segments.json` —— 翻译后的中文文本（保留英文术语）
- `frames/` —— 提取的关键帧图片（PPT 画面）

---

### 阶段 4：结果查看（输出）

**输出**：`./output/` 目录下的视觉文档

| 格式 | 文件示例 | 查看方式 |
|------|----------|----------|
| HTML | `*_vision_doc.html` | 直接用浏览器打开，图片已内嵌为 base64，可离线浏览 |
| Markdown | `*_vision_doc.md` | 用任意 Markdown 编辑器或 VS Code 预览 |
| PDF | `*_vision_doc.pdf` | 用 PDF 阅读器打开，适合打印与分享 |

HTML 视觉文档的页面结构：
- 顶部：视频标题、UP 主、BV 号
- 主体：按时间轴排列的 Slide 区块，左侧为 PPT 关键帧，右侧为对应的中文讲解文本
- 术语：英文专业术语自动高亮保留，不强行翻译

---

### 常用快捷模式

```bash
# 视频已有 B 站 AI 字幕：跳过语音转录，直接翻译
python main.py --url BV13T3x69Eqz --use-subtitle

# 已有本地音频：跳过下载
python main.py --url BV13T3x69Eqz --skip-download --audio ./audio.wav

# 已有本地视频：跳过下载，同时提取帧
python main.py --url BV13T3x69Eqz --skip-download --video ./video.mp4 --audio ./audio.wav

# 纯文本模式：不提取关键帧
python main.py --url BV13T3x69Eqz --skip-frames

# 生成 PDF
python main.py --url BV13T3x69Eqz --format pdf
```

---

## 三、实现功能

### 3.1 B 站视频下载与字幕获取（`src/extractors/bilibili.py`）

- **BV 号解析**：支持 `BVxxxxx`、`bilibili.com/video/BVxxxxx`、`b23.tv/BVxxxxx` 三种格式自动识别
- **视频信息获取**：通过 B 站公开 API (`x/web-interface/view`) 获取标题、UP 主、时长、CID
- **字幕智能获取**：通过 `x/player/wbi/v2` API 优先获取 B 站已有字幕（人工字幕 / AI 生成字幕），支持多语言选择（优先英文、中文）
- **视频下载**：调用 `yt-dlp` 下载最高可用画质，自动提取音频为 16kHz 单声道 WAV（Whisper 最优输入格式）
- **Cookie 支持**：可通过 `config.yaml` 配置 Cookie 文件，支持大会员高画质与付费内容

### 3.2 语音转文字（`src/processors/transcriber.py`）

| 引擎 | 运行方式 | 特点 | 推荐场景 |
|------|----------|------|----------|
| `faster-whisper` | 本地，支持 GPU (CUDA) | CTranslate2 加速，速度最快，支持 large-v3 | 有 NVIDIA GPU 的本地/服务器环境 |
| `whisper` | 本地，CPU/GPU | OpenAI 官方纯 Python 实现，兼容性好 | 通用本地环境 |
| `openai-api` | 云端 API | 无需本地模型，即开即用 | 无 GPU、追求便捷 |

- 输出格式支持：`json`（推荐，含完整时间戳）、`srt`、`vtt`、`txt`
- 支持词级时间戳（`word_timestamps`）
- 内置 `use_bili_subtitle()` 方法，可直接复用 B 站已有字幕，跳过本地转录

### 3.3 文本翻译（`src/processors/translator.py`）

| 引擎 | 成本 | 质量 | 特点 |
|------|------|------|------|
| `openai` | API 费用 | ★★★★★ | GPT-4o-mini / GPT-4o，上下文感知，支持术语保护列表 |
| `deep-translator` | 免费 | ★★★☆☆ | 基于 Google Translate，无需 API Key |
| `argos` | 免费 | ★★☆☆☆ | 完全离线，隐私安全，无需联网 |

- **术语保护**：通过 `config.yaml` 中的 `preserve_terms` 列表，自动保留英文专业术语不翻译（如 `sparse reward`、`topological quantum field theory`、`persistent homology` 等）
- **分批处理**：OpenAI 模式下自动按 30 段字幕分批，避免单请求 token 超限
- **双语输出**：可选保留原文与译文对照

### 3.4 关键帧 / PPT 画面提取（`src/extractors/frame_extractor.py`）

| 方法 | 原理 | 适用场景 |
|------|------|----------|
| `scene_change` | SSIM 结构相似度检测画面突变 | PPT 翻页、演讲者切换幻灯片 |
| `fixed_interval` | 固定时间间隔截图 | 画面变化平缓、需要均匀采样 |
| `ocr_trigger` | OCR 文字区域变化触发截图 | 文字驱动型视频（如代码演示） |

- 自动降采样加速计算（320×180 灰度图做 SSIM）
- 最小间隔过滤（`min_interval`），避免过度密集截图
- 输出尺寸控制（`max_width`），控制单张图片体积

### 3.5 视觉文档生成（`src/generators/vision_doc.py`）

- **时间对齐**：将关键帧与最近 60 秒窗口内的字幕片段自动配对
- **HTML 自包含**：所有图片内嵌为 base64 Data URI，单个 `.html` 文件即可离线浏览、邮件发送、网盘分享
- **Markdown 输出**：图片使用相对路径，便于版本控制与二次编辑
- **PDF 输出**：基于 WeasyPrint 将 HTML 渲染为 PDF，适合打印与学术归档
- **学术模板**：深色主题、代码高亮、MathJax 公式渲染、术语高亮样式

---

## 四、参考资料

### 核心依赖仓库

| 项目 | 链接 | 用途 |
|------|------|------|
| yt-dlp | https://github.com/yt-dlp/yt-dlp | B 站视频下载 |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | 本地 GPU 加速语音转录 |
| OpenAI Whisper | https://github.com/openai/whisper | 官方语音转录模型 |
| deep-translator | https://github.com/nidhaloff/deep-translator | 免费翻译引擎 |
| WeasyPrint | https://github.com/Kozea/WeasyPrint | HTML → PDF 渲染 |

### 学术参考

- Shehper et al. *What makes math problems hard for reinforcement learning: a case study.* NeurIPS 2025.  
  https://arxiv.org/abs/2502.07971
- Zhang et al. *AI-Driven Mathematical Discovery for the Andrews–Curtis Conjecture.* 2025.  
  https://openreview.net/forum?id=AI4Math
- Gukov, S. *AI tools for long-horizon sparse-reward tasks.* SAIR Foundation Science × AI Summit, 2026.  
  （B 站视频 BV13T3x69Eqz，本工具的典型处理对象）

---

**维护者**: [sakurayolove-svg](https://github.com/sakurayolove-svg)  
如有问题或建议，欢迎提交 Issue 或 PR。


---

## 真实案例

### BV13T3x69Eqz — Sergei Gukov: 面向长时程稀疏奖励任务的人工智能工具

- **视频时长**: 35 分钟 (2098s)
- **PPT定位**: 算法扫描前60秒，基于布局分析找到PPT真正开始位置
- **提取帧数**: 51 帧（PPT布局分数过滤 + 直方图去重）
- **处理时间**: < 30 秒
- **输出**: 6.0 MB 自包含 HTML 视觉文档

**PPT智能定位算法** (`src/extractors/frame_extractor.py`):
```python
# 不再假设"视频开头=PPT第一页"
# 1. 扫描前60秒，每秒采样一帧
# 2. 计算每帧的PPT布局分数（0-100）
#    - 文字密度（5-60%为PPT典型范围）
#    - 结构化布局（标题区+内容区+留白）
#    - 水平边缘密度（文字行特征）
#    - 颜色对比度
#    - 背景均匀性
# 3. 找到分数首次超过阈值的位置 = PPT真正开始
# 4. 从该位置提取关键帧，过滤掉片头/过渡/演讲者

ppt_start_time = detect_ppt_start(video_path, scan_duration=60, score_threshold=50)
# 返回: PPT开始时间（秒），不依赖时间假设
```

**布局分析 vs 时间假设**:
| 方法 | 问题 | 改进 |
|------|------|------|
| 前20秒强制保留 | 假设PPT在开头，可能保留片头 | ❌ |
| 场景变化检测 | 可能漏掉静态PPT封面 | ❌ |
| **布局分析** | **基于画面内容判断，找到真正的PPT开始** | ✅ |

**可调参数** (`config.yaml`):
```yaml
frame_extraction:
  ppt_scan_duration: 60.0      # 扫描前N秒定位PPT
  ppt_score_threshold: 50.0     # PPT开始判定阈值
  ppt_min_score: 35.0           # 过滤非PPT帧的最低分数
```

**如果算法误判**：降低 `ppt_score_threshold` 到 40 或 30，或改用VLM检测（`use_vlm: true`）。

### BV13T3x69Eqz — Sergei Gukov: 面向长时程稀疏奖励任务的人工智能工具

- **视频时长**: 35 分钟 (2098s)
- **提取帧数**: 27 帧（切片场景变化检测，3秒采样间隔）
- **处理时间**: < 30 秒
- **输出**: 2.0 MB 自包含 HTML 视觉文档

**提取函数** (`examples/extract_keyframes_sliced.py`):
```python
frames = extract_keyframes_sliced(
    video_path="./merged_video.mp4",
    output_dir="./frames",
    sample_interval_sec=3.0,   # 每3秒检查一帧
    diff_threshold=6.0,        # 灰度绝对差均值阈值
    min_interval_sec=8.0,      # 最小帧间隔
    max_frames=40              # 最多40帧
)
```

**核心优化**:
1. `cv2.CAP_PROP_POS_FRAMES` 跳帧读取，不顺序遍历
2. 160×90 灰度图做绝对差均值比较，比 SSIM 快 10 倍以上
3. 第一帧强制保存（确保封面/标题页）
4. 最多 40 帧上限，均匀覆盖全视频
