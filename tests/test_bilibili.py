"""
B站提取器单元测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from extractors.bilibili import BiliVideoExtractor


class TestBiliVideoExtractor:
    def test_parse_bvid(self):
        extractor = BiliVideoExtractor({})

        # 纯BV号
        assert extractor.parse_bvid("BV13T3x69Eqz") == "BV13T3x69Eqz"

        # 完整URL
        assert extractor.parse_bvid("https://www.bilibili.com/video/BV13T3x69Eqz") == "BV13T3x69Eqz"

        # 短链接
        assert extractor.parse_bvid("https://b23.tv/BV13T3x69Eqz") == "BV13T3x69Eqz"

        # 带参数的URL
        assert extractor.parse_bvid("https://www.bilibili.com/video/BV13T3x69Eqz?spm_id_from=333.337") == "BV13T3x69Eqz"

        # 无效输入
        assert extractor.parse_bvid("invalid") is None

    def test_get_video_info(self):
        extractor = BiliVideoExtractor({})
        info = extractor.get_video_info("BV13T3x69Eqz")

        assert info["bvid"] == "BV13T3x69Eqz"
        assert "title" in info
        assert "cid" in info
        assert info["duration"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
