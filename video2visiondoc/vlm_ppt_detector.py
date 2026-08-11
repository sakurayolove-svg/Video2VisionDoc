"""
【VLM PPT 检测（可选，供布局分析抽帧调用）】
本文件复制自 src/extractors/vlm_ppt_detector.py（初版实现），纳入 video2visiondoc 框架
作为同级可切换模块。原始文件保留于 src/ 未作修改。
"""
"""
VLM-based PPT画面检测器

使用视觉语言模型(VLM)判断视频帧是否为PPT幻灯片。
支持: Qwen-VL, LLaVA, InternVL, GPT-4V 等

为什么需要VLM:
- 传统算法(边缘检测/SSIM)容易误判封面/标题页(大字体、边缘少)
- VLM能直接理解"这是不是PPT"，准确率远高于启发式规则
- 能区分: PPT幻灯片 / 演讲者画面 / 过渡动画 / 黑屏 / B站UI
"""
import os
import cv2
import base64
from pathlib import Path
from typing import List, Dict, Optional


class VLMPPTDetector:
    """VLM PPT画面检测器"""

    def __init__(self, model: str = "qwen-vl-chat", api_key: Optional[str] = None):
        """
        参数:
            model: VLM模型名称
                - "qwen-vl-chat": 通义千问VL (推荐, 免费, 中文友好)
                - "llava-v1.5": LLaVA (开源, 本地部署)
                - "internvl-chat": InternVL (开源, 中文友好)
                - "gpt-4-vision": GPT-4V (API付费)
            api_key: API密钥 (仅对云端模型需要)
        """
        self.model = model
        self.api_key = api_key
        self._client = None

    def _encode_image(self, image_path: str) -> str:
        """将图片转为base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def is_ppt(self, image_path: str) -> bool:
        """
        判断单张图片是否为PPT幻灯片
        返回: True(是PPT) / False(不是PPT)
        """
        if self.model == "qwen-vl-chat":
            return self._check_qwen_vl(image_path)
        elif self.model == "gpt-4-vision":
            return self._check_gpt4v(image_path)
        elif self.model == "llava-v1.5":
            return self._check_llava(image_path)
        else:
            raise ValueError(f"不支持的VLM模型: {self.model}")

    def _check_qwen_vl(self, image_path: str) -> bool:
        """使用通义千问VL判断"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            # 或使用DashScope API:
            # import dashscope
            # dashscope.api_key = self.api_key

            # 这里展示API调用方式 (需要安装 dashscope)
            # 本地部署方式见: https://github.com/QwenLM/Qwen-VL

            # 简化版：使用API调用
            import requests

            img_b64 = self._encode_image(image_path)

            # DashScope API 调用
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "qwen-vl-chat",
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"image": f"data:image/jpeg;base64,{img_b64}"},
                                {"text": "这张图片是PPT幻灯片吗？请只回答“是”或“否”。PPT幻灯片通常包含标题、文字内容、图表或公式，背景简洁。"}
                            ]
                        }
                    ]
                }
            }

            resp = requests.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers=headers, json=payload, timeout=30
            )
            result = resp.json()
            answer = result.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")

            return "是" in answer or "yes" in answer.lower()

        except ImportError:
            print("[VLM] 请先安装 dashscope: pip install dashscope")
            return self._fallback_heuristic(image_path)
        except Exception as e:
            print(f"[VLM] API调用失败: {e}, 回退到启发式检测")
            return self._fallback_heuristic(image_path)

    def _check_gpt4v(self, image_path: str) -> bool:
        """使用GPT-4V判断"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            img_b64 = self._encode_image(image_path)

            response = client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Is this image a PowerPoint slide? Answer only YES or NO. A PPT slide typically has a title, text content, charts, or formulas on a clean background."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                        ]
                    }
                ],
                max_tokens=10
            )

            answer = response.choices[0].message.content
            return "YES" in answer.upper()

        except Exception as e:
            print(f"[VLM] GPT-4V失败: {e}, 回退到启发式检测")
            return self._fallback_heuristic(image_path)

    def _check_llava(self, image_path: str) -> bool:
        """使用LLaVA本地模型判断"""
        try:
            from llava.model.builder import load_pretrained_model
            from llava.mm_utils import get_model_name_from_path
            from llava.eval.run_llava import eval_model

            # LLaVA需要本地GPU部署
            # 参考: https://github.com/haotian-liu/LLaVA

            # 简化调用 (假设已部署服务)
            import requests
            img_b64 = self._encode_image(image_path)

            resp = requests.post("http://localhost:8000/eval", json={
                "image": img_b64,
                "prompt": "Is this a PowerPoint slide? Answer YES or NO only."
            }, timeout=30)

            answer = resp.json().get("answer", "")
            return "YES" in answer.upper()

        except Exception as e:
            print(f"[VLM] LLaVA失败: {e}, 回退到启发式检测")
            return self._fallback_heuristic(image_path)

    def _fallback_heuristic(self, image_path: str) -> bool:
        """启发式回退检测 (当VLM不可用时)"""
        img = cv2.imread(image_path)
        if img is None:
            return False

        small = cv2.resize(img, (320, 180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        # 文字区域占比
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        text_ratio = np.count_nonzero(binary) / binary.size

        # 边缘密度
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = np.count_nonzero(edges) / edges.size

        # 亮度标准差
        brightness_std = np.std(gray)

        # 封面/标题页判断（放宽标准）
        is_ppt = (text_ratio > 0.03 or edge_ratio > 0.002) and brightness_std > 12

        return is_ppt

    def filter_ppt_frames(self, frames: List[Dict]) -> List[Dict]:
        """
        从帧列表中过滤出PPT帧
        参数:
            frames: [{"timestamp": float, "path": str}, ...]
        返回:
            仅包含PPT帧的列表
        """
        ppt_frames = []
        for frame in frames:
            if self.is_ppt(frame["path"]):
                ppt_frames.append(frame)
                print(f"[VLM] ✓ PPT @{frame['timestamp']:.1f}s: {os.path.basename(frame['path'])}")
            else:
                print(f"[VLM] ✗ 非PPT @{frame['timestamp']:.1f}s: {os.path.basename(frame['path'])}")

        print(f"[VLM] 过滤完成: {len(ppt_frames)}/{len(frames)} 帧是PPT")
        return ppt_frames


# ========== 使用示例 ==========
if __name__ == "__main__":
    # 方式1: 使用通义千问VL (推荐, 需要DashScope API Key)
    # detector = VLMPPTDetector(model="qwen-vl-chat", api_key="your-dashscope-key")

    # 方式2: 使用GPT-4V (需要OpenAI API Key)
    # detector = VLMPPTDetector(model="gpt-4-vision", api_key="your-openai-key")

    # 方式3: 使用LLaVA本地部署
    # detector = VLMPPTDetector(model="llava-v1.5")

    # 方式4: 无VLM，纯启发式回退
    detector = VLMPPTDetector(model="qwen-vl-chat")  # 会自动回退到启发式

    # 测试
    # result = detector.is_ppt("./frames/frame_0000.000s.jpg")
    # print(f"是否为PPT: {result}")
