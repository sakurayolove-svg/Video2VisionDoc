"""
config.py —— 统一配置加载（v2 默认值 + config.yaml 覆盖）

设计原则：
    - 不读配置文件时，所有阶段的默认值就是 v2 推荐配置
      （与实战验证时激活的代码完全一致）；
    - config.yaml 中的每个 backend 选择项，可把对应阶段切换为
      v1 初版实现（位于 src/，被复用为备选后端）。

backend 选择总览：
    bilibili.method:        api（v2 默认）/ yt-dlp（v1）
    transcription.mode:     chunked（v2 默认）/ standard（v1 整段）
    frame_extraction.method: interval_dhash（v2 默认）/ ppt_layout（v1 布局分析）
    alignment.method:       per_slide（v2 默认）/ window（v1 ±60s 滑窗）
    translation.mode:       per_page（v2 默认）/ per_segment（v1 逐段）
    vision_doc.builder:     slide（v2 默认）/ legacy（v1 模板生成器）
"""

from pathlib import Path

import yaml

# v2 推荐默认值：与实战验证（BV13T3x69Eqz）时激活的配置完全一致
DEFAULT_CONFIG = {
    "bilibili": {
        "method": "api",          # api=v2 API直连（默认）; yt-dlp=v1
        "quality": 64,
        "timeout": 300,
        "threads": 4,
        "cookie_file": "",
    },
    "transcription": {
        "mode": "chunked",        # chunked=v2 分块防OOM（默认）; standard=v1 整段
        "engine": "faster-whisper",
        "model": "small",         # 4GB 内存验证值；有 GPU 可改 large-v3
        "language": "en",
        "device": "cpu",
        "compute_type": "int8",
        "chunk_seconds": 300,
        "beam_size": 3,
        "initial_prompt": "",
    },
    "frame_extraction": {
        "method": "interval_dhash",  # interval_dhash=v2（默认）; ppt_layout=v1 布局分析
        "sample_interval": 10,
        "hash_threshold": 40,
        # v1 ppt_layout 参数（切换后生效）
        "scene_threshold": 0.12,
        "interval": 25,
        "max_width": 1280,
        "ppt_scan_duration": 60.0,
        "ppt_score_threshold": 50.0,
        "ppt_min_score": 35.0,
    },
    "alignment": {
        "method": "per_slide",    # per_slide=v2 按页（默认）; window=v1 ±60s 滑窗
        "window_seconds": 60,
        "exclude_frames": [],     # 剔除帧序号（1 起），如演讲者镜头
    },
    "translation": {
        "mode": "per_page",       # per_page=v2 按页（默认）; per_segment=v1 逐段
        "engine": "llm",          # llm=v2 OpenAI兼容（默认）; openai/deep-translator/argos=v1
        "target_language": "中文",
        "preserve_terms": [
            "sparse reward", "long horizon", "reinforcement learning",
            "Montezuma's Revenge", "Andrews-Curtis conjecture",
            "Ramsey numbers", "DQN", "Go-Explore", "evaluator",
        ],
        "openai": {               # v1 openai 引擎参数（切换后生效）
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
    },
    "vision_doc": {
        "builder": "slide",       # slide=v2 自包含HTML（默认）; legacy=v1 模板生成器
        "output_format": "html",
        "template": "academic",
        "pdf": False,
        # v1 legacy 参数（切换后生效）
        "theme_color": "#3b82f6",
        "include_timeline": True,
        "include_frames": True,
    },
    "output": {
        "directory": "./output",
    },
}


def load_config(config_path: str = None) -> dict:
    """
    加载配置：v2 默认值为基础，config.yaml 中的键递归覆盖。
    不传路径时依次尝试 ./config.yaml 与仓库根目录 config.yaml。
    """
    import copy
    config = copy.deepcopy(DEFAULT_CONFIG)

    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    else:
        candidates.append(Path("config.yaml"))
        candidates.append(Path(__file__).parent.parent / "config.yaml")

    for path in candidates:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            _deep_update(config, user_cfg)
            break
    return config


def _deep_update(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
