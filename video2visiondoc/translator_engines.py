"""
【v1 后端：逐段翻译（openai / deep-translator / argos）】
本文件复制自 src/processors/translator.py（v1 初版实现），纳入 video2visiondoc 框架
作为同级可切换后端。原始文件保留于 src/ 未作修改。
"""
"""
翻译模块
支持: deep-translator(免费), openai(付费高质量), argos(离线)
"""
import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional


class TextTranslator:
    """文本翻译器"""

    def __init__(self, config: Dict):
        self.config = config.get("translation", {})
        self.engine = self.config.get("engine", "openai")
        self.target_language = self.config.get("target_language", "zh-CN")
        self.keep_original = self.config.get("keep_original", True)
        self.preserve_terms = self.config.get("preserve_terms", [])
        self.openai_cfg = self.config.get("openai", {})
        self._client = None

    def _get_openai_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
            api_key = self.openai_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
            base_url = self.openai_cfg.get("base_url", "https://api.openai.com/v1")
            if not api_key:
                raise ValueError("OpenAI API key 未设置")
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            return self._client
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

    def translate_segments(self, segments: List[Dict], output_dir: str) -> Dict:
        """
        翻译转录片段
        返回: {
            "segments": [
                {"start": float, "end": float, "original": str, "translated": str},
                ...
            ],
            "full_original": str,
            "full_translated": str,
            "output_file": str,
        }
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if self.engine == "openai":
            translated = self._translate_openai(segments)
        elif self.engine == "deep-translator":
            translated = self._translate_deep_translator(segments)
        elif self.engine == "argos":
            translated = self._translate_argos(segments)
        else:
            raise ValueError(f"不支持的翻译引擎: {self.engine}")

        # 保存结果
        output_file = output_path / "translated_segments.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(translated, f, ensure_ascii=False, indent=2)

        translated["output_file"] = str(output_file)
        print(f"[翻译] 结果已保存: {output_file}")
        return translated

    def _translate_openai(self, segments: List[Dict]) -> Dict:
        """使用 OpenAI API 翻译（推荐，质量最高）"""
        client = self._get_openai_client()
        model = self.openai_cfg.get("model", "gpt-4o-mini")
        temperature = self.openai_cfg.get("temperature", 0.3)
        max_tokens = self.openai_cfg.get("max_tokens", 4096)

        # 构建术语保护规则
        term_rules = "\n".join([
            f"- 保留英文术语: '{term}' 不翻译"
            for term in self.preserve_terms
        ])

        system_prompt = f"""你是一位专业的学术翻译助手。请将以下视频字幕翻译成{self.target_language}。

要求：
1. 保持学术严谨性，术语准确
2. 保留所有英文专业术语和缩写（如 sparse reward, reinforcement learning 等）
3. 翻译应自然流畅，符合中文表达习惯
4. 如果原文是中文，则直接返回原文

术语保护规则：
{term_rules}

输出格式为 JSON：
{{"segments": [{{"start": 时间, "end": 时间, "original": "原文", "translated": "译文"}}]}}
"""

        # 分批处理，避免token超限
        batch_size = 30
        all_translated = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i+batch_size]
            batch_json = json.dumps(batch, ensure_ascii=False)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请翻译以下字幕片段:\n{batch_json}"},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            all_translated.extend(result.get("segments", []))

        full_original = " ".join([s.get("original", s.get("text", "")) for s in segments])
        full_translated = " ".join([s.get("translated", "") for s in all_translated])

        return {
            "segments": all_translated,
            "full_original": full_original,
            "full_translated": full_translated,
        }

    def _translate_deep_translator(self, segments: List[Dict]) -> Dict:
        """使用 deep-translator 免费翻译"""
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            raise ImportError("请安装 deep-translator: pip install deep-translator")

        translator = GoogleTranslator(source="auto", target=self.target_language[:2])

        translated_segments = []
        for seg in segments:
            text = seg.get("text", "")
            # 保护术语
            protected = text
            placeholders = {}
            for idx, term in enumerate(self.preserve_terms):
                if term in protected:
                    placeholder = f"__TERM_{idx}__"
                    placeholders[placeholder] = term
                    protected = protected.replace(term, placeholder)

            try:
                translated = translator.translate(protected)
            except Exception:
                translated = text  # 失败时保留原文

            # 还原术语
            for placeholder, term in placeholders.items():
                translated = translated.replace(placeholder, term)

            translated_segments.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "original": text,
                "translated": translated,
            })

        full_original = " ".join([s["original"] for s in translated_segments])
        full_translated = " ".join([s["translated"] for s in translated_segments])

        return {
            "segments": translated_segments,
            "full_original": full_original,
            "full_translated": full_translated,
        }

    def _translate_argos(self, segments: List[Dict]) -> Dict:
        """使用 Argos Translate 离线翻译"""
        try:
            import argostranslate.package
            import argostranslate.translate
        except ImportError:
            raise ImportError("请安装 argostranslate: pip install argostranslate")

        # 自动下载语言包
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()

        # 尝试找到合适的语言包
        from_code = "en"
        to_code = self.target_language[:2]

        package_to_install = next(
            (pkg for pkg in available_packages
             if pkg.from_code == from_code and pkg.to_code == to_code),
            None
        )

        if package_to_install:
            argostranslate.package.install_from_path(package_to_install.download())

        translated_segments = []
        for seg in segments:
            text = seg.get("text", "")
            try:
                translated = argostranslate.translate.translate(text, from_code, to_code)
            except Exception:
                translated = text

            translated_segments.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "original": text,
                "translated": translated,
            })

        return {
            "segments": translated_segments,
            "full_original": " ".join([s["original"] for s in translated_segments]),
            "full_translated": " ".join([s["translated"] for s in translated_segments]),
        }
