# Video2VisionDoc

**作者**: [sakurayolove-svg](https://github.com/sakurayolove-svg)  
**许可证**: BSD-3-Clause

将 B 站学术/演讲/课程视频一键转换为带时间轴、带 PPT 画面的视觉文档。

---

## 一、基本信息

Video2VisionDoc 是一个面向学术视频处理的自动化工具链，核心目标是将 Bilibili 上的演讲、课程、学术报告等长视频，自动提取语音文本、翻译为中文、捕获关键帧（PPT 画面），最终组合成一份可离线浏览、可分享、可检索的视觉文档。

典型应用场景：
- 国际学术会议/讲座的语音内容转录与中文可视化整理
- 在线课程的知识要点结构化归档
- 技术分享视频的快速概览与检索

### 统一流水线与可切换后端

整个工具是一条六阶段流水线：**下载 → 转写 → 翻译 → 关键帧 → 对齐 → 文档生成**。每个阶段都有两套可切换的实现后端：

| 阶段 | v2 后端（默认，实战验证） | v1 后端（初版，复用保留） |
|------|--------------------------|--------------------------|
| 1. 下载 | **API 直连**：`view`→`playurl` 取 DASH 流，抗 B 站反爬(412) | yt-dlp 下载（支持 Cookie/高画质） |
| 2. 转写 | **分块转写**：5 分钟一块 + VAD + int8，防 OOM，断点续跑 | 整段转写（faster-whisper / whisper / openai-api 多引擎） |
| 3. 翻译 | **按页翻译**：OpenAI 兼容 API，页内上下文连贯 | 逐段翻译（openai / deep-translator / argos） |
| 4. 关键帧 | **均匀抽帧 + dHash 去重**：10 秒一帧，256 bit 哈希 | PPT 布局分析 + 场景变化 + 直方图去重 |
| 5. 对齐 | **按 PPT 页时间窗**：一页 PPT 对应一段讲解 | ±60 秒滑窗配对 |
| 6. 文档 | **按页自包含 HTML**：一页一截图一段译稿 | 模板生成器（academic/minimal，HTML/MD/PDF） |

- v2 后端位于 `video2visiondoc/` 包，是在真实任务（BV13T3x69Eqz，35 分钟英文演讲、**无字幕**、4GB 内存 CPU 容器）中完整验证过的实现，**为默认推荐**；
- v1 后端位于 `src/` 目录，全部保留未删，通过 `video2visiondoc/backends.py` 适配层复用；
- **当配置全部为 v2 默认值时，激活的代码与 v2 实战验证版完全一致**；把任一阶段切到 v1，只有该阶段改走 `src/` 下的对应模块。

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
# v2 默认后端的最小依赖：requests / faster-whisper / Pillow / numpy
# v1 备选后端的追加依赖见 requirements.txt 下半部分

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

**输入**：`config.yaml`（根据你的环境和需求修改；不修改时全部为 v2 默认值）

后端切换项（每个阶段独立切换）：

```yaml
bilibili:
  method: "api"              # api(v2默认,抗反爬) / yt-dlp(v1,支持Cookie)

transcription:
  mode: "chunked"            # chunked(v2默认,分块防OOM) / standard(v1整段)
  model: "small"             # 4GB内存验证值; 有GPU可改 large-v3
  initial_prompt: ""         # 领域提示词, 显著改善专有名词识别

translation:
  mode: "per_page"           # per_page(v2默认,按页) / per_segment(v1逐段)
  engine: "llm"              # llm(v2,OpenAI兼容) / openai / deep-translator / argos

frame_extraction:
  method: "interval_dhash"   # interval_dhash(v2默认) / ppt_layout(v1布局分析)

alignment:
  method: "per_slide"        # per_slide(v2默认,按页) / window(v1滑窗)
  exclude_frames: []         # 需剔除的帧序号(1起), 如演讲者镜头

vision_doc:
  builder: "slide"           # slide(v2默认,按页HTML) / legacy(v1模板)
  pdf: false                 # v2: 同时输出PDF(需playwright或weasyprint)
```

翻译 API（v2 `llm` 引擎，任意 OpenAI 兼容端点）通过环境变量配置：

```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.openai.com/v1"   # 可换 Moonshot/DeepSeek/本地vLLM
export LLM_MODEL="gpt-4o-mini"
# 未设置 LLM_API_KEY 时优雅降级：保留英文原文，不中断流水线
```

低内存环境提示：4GB 内存请保持 `model: "small"` 或更小；Whisper 模型下载慢可设
`HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1`。

**输出**：一份针对你本地环境调优的 `config.yaml`。

---

### 阶段 3：执行处理（输入 → 中间产物）

**输入**：B 站视频 URL 或 BV 号。两个等价入口：

```bash
# 入口 A：v2 框架命令行（推荐）
python -m video2visiondoc BV13T3x69Eqz -o ./output

# 入口 B：v1 兼容入口（参数接口与初版一致）
python main.py --url BV13T3x69Eqz --output ./output

# 切换 v1 后端示例（命令行覆盖 config.yaml）
python -m video2visiondoc BV13T3x69Eqz \
    --download yt-dlp --frames ppt_layout \
    --translate-mode per_segment --builder legacy
```

**中间产物**（输出到 `./output/work/`）：
- `merged.mp4` / `audio_16k.wav` —— 合并视频与 16kHz 单声道音频
- `transcript.json`（及 `transcript_partial.json`）—— 带时间戳的转录，分块模式每块落盘可断点续跑
- `translated.json` —— 按页对齐+翻译结果，同样支持断点续翻
- `slides/slide_XX.jpg` —— 去重后的 PPT 关键帧

---

### 阶段 4：结果查看（输出）

**输出**：`./output/` 目录下的视觉文档

| 后端 | 文件示例 | 查看方式 |
|------|----------|----------|
| v2 `slide` | `*_视觉文档.html`（+ 可选 `.pdf`） | 单文件自包含（图片 base64 内嵌），浏览器直接打开，可离线分享 |
| v1 `legacy` | `*_vision_doc.html` / `.md` / `.pdf` | HTML 自包含；Markdown 图片用相对路径便于版本控制 |

v2 视觉文档的页面结构：
- 顶部：视频标题、UP 主、BV 号
- 主体：每页一节——PPT 关键帧截图（标注视频时间段）+ 该页期间讲解内容的中文译稿
- 术语：英文专业术语保留不译（`preserve_terms` 可配）

---

### 常用快捷模式

```bash
# 视频已有 B 站 AI 字幕：跳过语音转录，直接翻译
python -m video2visiondoc BV13T3x69Eqz --use-subtitle

# 已有本地音视频：跳过下载
python -m video2visiondoc BV13T3x69Eqz --skip-download \
    --video ./video.mp4 --audio ./audio.wav

# 已有转录：跳过转写
python -m video2visiondoc BV13T3x69Eqz --skip-download \
    --video ./video.mp4 --transcript ./transcript.json

# 剔除开场的演讲者镜头帧（第 2、3 帧，1 起计数）
python -m video2visiondoc BV13T3x69Eqz --exclude-frames 2 3

# 领域提示词改善识别 + 输出 PDF
python -m video2visiondoc BV13T3x69Eqz \
    --prompt "Talk on sparse rewards in reinforcement learning" --pdf

# 纯文本模式：不提取关键帧
python -m video2visiondoc BV13T3x69Eqz --skip-frames
```

---

## 三、实现功能

### 3.1 B 站视频下载与字幕获取

**v2 后端（默认）：API 直连**（`video2visiondoc/downloader.py`）

- **BV 号解析**：支持 `BVxxxxx`、`bilibili.com/video/BVxxxxx`、`b23.tv/BVxxxxx` 及 `list/watchlater?bvid=` 等带参数 URL
- **两步 API**：`x/web-interface/view` 取标题/时长/cid/UP 主 → `x/player/playurl` 取 DASH 音视频流（未登录最高 480P，对 PPT 画面与语音识别足够）
- **抗反爬**：带 UA + Referer 直接下载流文件，规避 yt-dlp 直连常见的 HTTP 412
- **ffmpeg 合并**：video.m4s + audio.m4s → mp4，并提取 16kHz 单声道 WAV（Whisper 最优输入）

**v1 后端（备选）：yt-dlp**（`src/extractors/bilibili.py`）

- 支持 Cookie 文件（大会员高画质/付费内容）、并发分片、更多画质选择
- **字幕获取**：`x/player/wbi/v2` 获取 B 站人工/AI 字幕（两个后端都可用，`--use-subtitle`）

### 3.2 语音转文字

**v2 后端（默认）：分块转写**（`video2visiondoc/transcriber.py`）

实战背景：4GB 内存容器中，medium/small 模型整段转写 35 分钟音频均被 OOM 杀掉。

- ffmpeg `-c copy` 把音频切成 5 分钟一块，逐块转写，内存占用恒定
- VAD 过滤静音提速；int8 量化；`initial_prompt` 领域提示词改善专有名词
- 每块完成即落盘 `transcript_partial.json`，崩溃后可断点续跑
- 时间戳自动加块偏移，拼成全局时间轴

**v1 后端（备选）：整段多引擎**（`src/processors/transcriber.py`）

| 引擎 | 运行方式 | 特点 | 推荐场景 |
|------|----------|------|----------|
| `faster-whisper` | 本地，支持 GPU (CUDA) | CTranslate2 加速，支持 large-v3 | 有 NVIDIA GPU 的环境 |
| `whisper` | 本地，CPU/GPU | OpenAI 官方实现，兼容性好 | 通用本地环境 |
| `openai-api` | 云端 API | 无需本地模型 | 无 GPU、追求便捷 |

- 输出格式：`json`（含完整时间戳）/ `srt` / `vtt` / `txt`，支持词级时间戳
- `use_bili_subtitle()` 可直接复用 B 站已有字幕，跳过本地转录

### 3.3 文本翻译

**v2 后端（默认）：按页翻译**（`video2visiondoc/translator.py`）

- 以"一页 PPT 的完整讲解"为粒度调用 LLM，术语与指代在页内一致（优于逐句翻译）
- 任意 OpenAI 兼容端点（`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`），不写死供应商
- 无 API Key 时优雅降级保留原文；每页翻译完即落盘，支持断点续翻
- `preserve_terms` 术语保护列表注入 prompt

**v1 后端（备选）：逐段三引擎**（`src/processors/translator.py`）

| 引擎 | 成本 | 质量 | 特点 |
|------|------|------|------|
| `openai` | API 费用 | ★★★★★ | GPT-4o-mini / GPT-4o，分批 30 段防 token 超限 |
| `deep-translator` | 免费 | ★★★☆☆ | 基于 Google Translate，无需 API Key |
| `argos` | 免费 | ★★☆☆☆ | 完全离线，隐私安全 |

### 3.4 关键帧 / PPT 画面提取

**v2 后端（默认）：均匀抽帧 + dHash 去重**（`video2visiondoc/keyframes.py`）

实战背景：纯场景变化检测阈值难调——高了漏版式相近的翻页，低了混入演讲者镜头，静态封面可能完全漏掉。

- 每 10 秒均匀抽帧（`fps=1/10`），保证不遗漏任何页面
- dHash（16×16，256 bit）与上一个"保留帧"比较汉明距离，超过阈值（默认 40）才保留——避免与相邻帧比较时的累积漂移
- 实测：35 分钟视频 210 帧 → 27 帧，演讲者镜头与 PPT 自然区分

**v1 后端（备选）：PPT 布局分析**（`src/extractors/frame_extractor.py`）

- 扫描前 60 秒，按文字密度/结构化布局/边缘密度/对比度/背景均匀性计算 PPT 布局分数，定位 PPT 真正开始位置（不假设"开头=第一页"）
- 场景变化 + 固定间隔双路采样，PPT 分数过滤非 PPT 帧，直方图去重
- 可选 VLM 检测（`src/extractors/vlm_ppt_detector.py`）

### 3.5 转写文本与画面对齐

**v2 后端（默认）：按 PPT 页时间窗**（`video2visiondoc/aligner.py`）

- 每页 PPT 的停留时间段 `[t_i, t_{i+1})` 内的全部转写段归为该页——翻译粒度与文档结构天然一致
- `exclude_frames` 可剔除演讲者纯镜头帧，其时间窗并入前一页

**v1 后端（备选）：±60 秒滑窗**（`video2visiondoc/aligner.py` 的 `align_window`）

- 每帧配对前后 60 秒内的字幕，与初版 `VisionDocGenerator` 语义一致

### 3.6 视觉文档生成

**v2 后端（默认）：按页自包含 HTML**（`video2visiondoc/docbuilder.py`）

- 每页一节：页码 + 视频时间段 + PPT 截图 + 该页中文译稿
- 图片全部内嵌为 base64 Data URI，单文件离线浏览/邮件/网盘分享
- `--pdf` 时经 Playwright（或 WeasyPrint）输出 A4 PDF

**v1 后端（备选）：模板生成器**（`src/generators/vision_doc.py`）

- academic / minimal 模板，HTML / Markdown / PDF 三格式
- 深色主题、代码高亮、MathJax 公式渲染、术语高亮

---

## 四、参考资料

### 核心依赖仓库

| 项目 | 链接 | 用途 |
|------|------|------|
| yt-dlp | https://github.com/yt-dlp/yt-dlp | B 站视频下载（v1 后端） |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | 本地 GPU 加速语音转录 |
| OpenAI Whisper | https://github.com/openai/whisper | 官方语音转录模型（v1 后端） |
| deep-translator | https://github.com/nidhaloff/deep-translator | 免费翻译引擎（v1 后端） |
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

### BV13T3x69Eqz — Sergei Gukov: 面向长时程稀疏奖励任务的人工智能工具（v2 后端）

- **视频时长**: 35 分钟 (2098s)，无任何字幕
- **转写**: small 模型 5 分钟分块，366 段（4GB 内存 CPU 容器稳定跑完）
- **提取帧数**: 210 帧均匀采样 → dHash 去重后 27 帧（剔除 2 个演讲者镜头后 25 页）
- **对齐**: 按 PPT 页时间窗，第 2 页（稀疏奖励/长时程）窗口 30–240s 共 497 词
- **输出**: 按页自包含 HTML 视觉文档（25 页 PPT + 中文译稿）

**v2 抽帧算法** (`video2visiondoc/keyframes.py`):
```python
# 1. ffmpeg fps=1/10 均匀抽帧，不漏静态页
# 2. dHash(16×16) 与上一个"保留帧"比汉明距离 > 40 才保留
#    —— 与相邻帧比较会在画面缓变时累积漂移，与保留帧比较不会
slides = KeyframeExtractor(sample_interval=10, hash_threshold=40)
slides = slides.extract(video_path, out_dir)   # 210 帧 → 27 帧
```

**v2 分块转写** (`video2visiondoc/transcriber.py`):
```python
# 整段转写 35 分钟音频在 4GB 容器中必 OOM（medium/small 均验证）
# 切成 5 分钟一块逐块转写，每块落盘 transcript_partial.json
segments = ChunkedTranscriber(
    model_size="small", chunk_seconds=300,
    initial_prompt="Talk on sparse rewards in RL, topology.",
).transcribe(audio_path, workdir)
```

### BV13T3x69Eqz — Sergei Gukov（v1 后端：PPT布局分析）

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

### BV13T3x69Eqz — Sergei Gukov（v1 后端：切片场景变化）

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
