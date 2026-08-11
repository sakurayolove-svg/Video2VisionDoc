"""
translator.py —— 按页翻译（OpenAI 兼容 API）

设计要点：
    - 以“页”为粒度翻译（见 aligner.py），一次请求翻译一页 PPT 的
      全部口语文本，术语与指代在页内保持一致；
    - 支持任意 OpenAI 兼容端点（OpenAI / Moonshot / DeepSeek / 本地 vLLM），
      通过环境变量配置，不在代码里写死供应商；
    - 无 API Key 时优雅降级：保留英文原文，并在文档中标注“未翻译”；
    - 术语保护：prompt 中要求保留 preserve_terms 列表内的英文术语。

环境变量：
    LLM_API_KEY   API 密钥（必需，否则跳过翻译）
    LLM_BASE_URL  端点地址（默认 https://api.openai.com/v1）
    LLM_MODEL     模型名（默认 gpt-4o-mini）

依赖：requests。
"""

import json
import os
import time
from pathlib import Path

import requests

DEFAULT_TERMS = [
    "sparse reward", "long horizon", "reinforcement learning",
    "Montezuma's Revenge", "Andrews-Curtis conjecture",
    "Ramsey numbers", "DQN", "Go-Explore", "evaluator",
]


class SlideTranslator:
    """按页翻译器"""

    def __init__(self,
                 target_lang: str = "中文",
                 preserve_terms: list = None,
                 max_retries: int = 3):
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL",
                                       "https://api.openai.com/v1")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.target_lang = target_lang
        self.preserve_terms = preserve_terms or DEFAULT_TERMS
        self.max_retries = max_retries

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _build_prompt(self, text: str) -> str:
        terms = "、".join(self.preserve_terms)
        return (
            f"你是学术演讲翻译专家。下面是某页幻灯片对应的英文演讲口述文本"
            f"（由语音识别得到，可能有个别识别错误）。\n"
            f"请将其翻译为通顺、忠实的{self.target_lang}，要求：\n"
            f"1. 保持口语讲解的叙述顺序与完整信息，不要总结、不要遗漏；\n"
            f"2. 修正明显的语音识别错误（结合上下文判断）；\n"
            f"3. 以下专业术语保留英文不译：{terms}；\n"
            f"4. 直接输出译文，不要任何解释。\n\n"
            f"英文原文：\n{text}"
        )

    def _call_api(self, prompt: str) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        last_err = None
        for attempt in range(self.max_retries):
            try:
                r = requests.post(url, headers=headers, json=payload,
                                  timeout=120)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:  # noqa: BLE001 —— 重试后仍失败再抛出
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"翻译 API 调用失败（重试 {self.max_retries} 次）: {last_err}")

    def translate_blocks(self, blocks: list, workdir: str) -> list:
        """
        逐页翻译 blocks（aligner 的输出），在原 dict 上增加 "text_zh" 字段。
        无 API Key 时 text_zh 置为原文并标注。
        增量写入 workdir/translated.json，支持中断后继续。
        """
        workdir = Path(workdir)
        out_path = workdir / "translated.json"
        done = {}
        if out_path.exists():
            done = {b["index"]: b for b in
                    json.load(open(out_path, encoding="utf-8"))}

        if not self.available:
            print("  未设置 LLM_API_KEY，跳过翻译（保留英文原文）")

        for b in blocks:
            if b["index"] in done:  # 断点续翻
                b["text_zh"] = done[b["index"]].get("text_zh", "")
                continue
            if not self.available or not b["text"]:
                b["text_zh"] = b["text"]
            else:
                b["text_zh"] = self._call_api(self._build_prompt(b["text"]))
                print(f"  第 {b['index']} 页翻译完成 "
                      f"({len(b['text'])} → {len(b['text_zh'])} 字符)")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(blocks, f, ensure_ascii=False, indent=1)
        return blocks
