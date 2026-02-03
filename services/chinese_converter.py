"""
简繁体转换工具
用于搜索时的简繁体互通
"""
import re
from pathlib import Path
from loguru import logger


class ChineseConverter:
    """简繁体转换器"""

    def __init__(self):
        self.traditional_to_simplified = {}
        self.simplified_to_traditional = {}
        self._load_conversion_table()

    def _load_conversion_table(self):
        """加载简繁体对照表"""
        try:
            # 从 webui/static/ChineseCharacters.txt 加载
            table_path = Path(__file__).parent.parent / "webui" / "static" / "ChineseCharacters.txt"

            if not table_path.exists():
                logger.warning(f"简繁体对照表文件不存在: {table_path}")
                return

            with open(table_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or '(' not in line:
                        continue

                    # 格式: 繁体(简体)
                    match = re.match(r'^(.+)\((.+)\)$', line)
                    if match:
                        traditional = match.group(1)
                        simplified = match.group(2)

                        # 建立双向映射
                        if traditional != simplified:
                            self.traditional_to_simplified[traditional] = simplified
                            self.simplified_to_traditional[simplified] = traditional

            logger.info(f"简繁体对照表加载成功: {len(self.traditional_to_simplified)} 个字符对")

        except Exception as e:
            logger.error(f"加载简繁体对照表失败: {e}")

    def to_simplified(self, text: str) -> str:
        """将繁体转换为简体"""
        result = []
        for char in text:
            if char in self.traditional_to_simplified:
                result.append(self.traditional_to_simplified[char])
            else:
                result.append(char)
        return ''.join(result)

    def to_traditional(self, text: str) -> str:
        """将简体转换为繁体"""
        result = []
        for char in text:
            if char in self.simplified_to_traditional:
                result.append(self.simplified_to_traditional[char])
            else:
                result.append(char)
        return ''.join(result)

    def get_search_variants(self, text: str) -> list:
        """
        获取搜索词的所有变体（简繁体）
        返回: [原文, 简体版本, 繁体版本]
        去重后返回
        """
        variants = [text]

        # 转换为简体
        simplified = self.to_simplified(text)
        if simplified != text and simplified not in variants:
            variants.append(simplified)

        # 转换为繁体
        traditional = self.to_traditional(text)
        if traditional != text and traditional not in variants:
            variants.append(traditional)

        return variants


# 全局转换器实例
_converter = None


def get_converter() -> ChineseConverter:
    """获取转换器单例"""
    global _converter
    if _converter is None:
        _converter = ChineseConverter()
    return _converter
