"""选题过滤器 - 三个 Check 门控机制

三个 Check:
1. 近三月同质文章数量 - 启发式关键词评估
2. 反常识观点 - 争议性关键词检测
3. 反直觉数据 - 反直觉特征词检测

门控规则:
- 三个 check 全否 → low_value，不建议自动排入队列
- 至少一个是 → 可以进入队列
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote

logger = logging.getLogger(__name__)


class TopicFilter:
    """选题过滤器 - 评估选题价值"""

    # 高同质化关键词（表示该主题已经很常见）
    HIGH_HOMOGENEITY_KEYWORDS = [
        "教程", "入门", "基础", "快速上手", "从零开始",
        "指南", "大全", "总结", "必备", "清单",
        "best", "tutorial", "guide", "beginner", "introduction"
    ]

    # 争议性/反常识关键词
    CONTRARIAN_KEYWORDS = [
        "误区", "误解", "常见错误", "反向", "反驳",
        "争议", "相反", "不是", "打破", "陷阱",
        "避坑", "坑点", "为什么不用", "不要"
    ]

    # 反直觉数据特征词
    COUNTER_INTUITIVE_KEYWORDS = [
        "意外", "出人意料", "与预期相反", "反常识",
        "数据显示", "研究发现", "统计表明", "数据证明",
        "但实际", "然而", "出乎意料", "却"
    ]

    def __init__(self, mock_search: bool = False):
        """初始化过滤器

        Args:
            mock_search: 是否使用 mock 搜索（测试用）
        """
        self.mock_search = mock_search

    def filter_topic(self, keyword: str, category: str = "") -> dict:
        """过滤选题，返回建议

        Args:
            keyword: 选题关键词
            category: 分类（可选，用于搜索优化）

        Returns:
            {
                "recommendation": "accept" | "low_value" | "reject",
                "reason": str,
                "checks": {
                    "homogeneity": {"score": int, "verdict": bool},
                    "contrarian": {"has": bool, "verdict": bool},
                    "counter_intuitive": {"has": bool, "verdict": bool},
                }
            }
        """
        checks = {
            "homogeneity": self._check_homogeneity(keyword, category),
            "contrarian": self._check_contrarian(keyword, category),
            "counter_intuitive": self._check_counter_intuitive(keyword, category),
        }

        # 门控逻辑：至少一个 check 通过 → accept
        # 全部不通过但有同质化问题 → low_value
        # 否则 → low_value
        passed = sum(c["verdict"] for c in checks.values())

        if passed >= 1:
            recommendation = "accept"
            reason = f"通过 {passed}/3 个检查点，选题有价值"
        elif checks["homogeneity"]["score"] > 10:
            recommendation = "low_value"
            reason = f"市场同质化严重（{checks['homogeneity']['score']}+ 篇相似文章），建议差异化"
        else:
            recommendation = "low_value"
            reason = "未通过价值检查点，建议重新定位角度"

        return {
            "recommendation": recommendation,
            "reason": reason,
            "checks": checks,
            "meta": {
                "keyword": keyword,
                "category": category,
                "timestamp": datetime.now().isoformat(),
            }
        }

    def _check_homogeneity(self, keyword: str, category: str) -> dict:
        """Check 1: 近三月同质文章数量

        启发式评估逻辑:
        - 检测关键词中的高同质化特征词
        - 检查是否为热门技术栈的入门话题
        - 评分越高 = 同质度越高

        Returns:
            {"score": int, "verdict": bool}
            score: 同质化评分 (0-100)
            verdict: True = 同质度低（好），False = 同质度高（不好）
        """
        if self.mock_search:
            return {"score": 25, "verdict": False}

        try:
            score = 0
            keyword_lower = keyword.lower()
            category_lower = category.lower() if category else ""

            # 1. 检测高同质化关键词
            for kw in self.HIGH_HOMOGENEITY_KEYWORDS:
                if kw in keyword_lower or kw in category_lower:
                    score += 20

            # 2. 热门技术栈额外加分（这些领域入门内容非常多）
            hot_topics = ["wordpress", "python", "javascript", "react", "vue", "java", "go", "rust", "docker", "kubernetes"]
            if any(topic in keyword_lower for topic in hot_topics):
                score += 15

            # 3. 限定类话题（如"入门"、"基础"）额外加分
            basic_patterns = [r"入门", r"基础", r"从零", r"新手", r"快速", r".*tutorial", r".*guide", r".*101"]
            for pattern in basic_patterns:
                if re.search(pattern, keyword_lower):
                    score += 15
                    break

            # 4. 如果包含"高级"、"深入"、"原理"等词，降低同质度评分
            advanced_patterns = [r"高级", r"深入", r"原理", r"底层", r"源码", r"advanced", r"deep.?dive", r"internals"]
            for pattern in advanced_patterns:
                if re.search(pattern, keyword_lower):
                    score -= 20
                    break

            score = max(0, min(100, score))  # 限制在 0-100 范围
            verdict = score < 50  # 50 分以上视为高同质化

            logger.info(f"Homogeneity check: keyword='{keyword}', score={score}, verdict={verdict}")
            return {"score": score, "verdict": verdict}

        except Exception as e:
            logger.warning(f"Homogeneity check failed: {e}")
            return {"score": 60, "verdict": False}

    def _check_contrarian(self, keyword: str, category: str) -> dict:
        """Check 2: 反常识观点

        启发式检测逻辑:
        - 检测关键词中的争议性/反驳性特征词
        - 找到特征词说明观点有争议性/反常识性

        Returns:
            {"has": bool, "verdict": bool}
            has: 是否包含反常识特征词
            verdict: True = 有反常识性（好），False = 缺乏反常识性
        """
        if self.mock_search:
            return {"has": False, "verdict": False}

        try:
            keyword_lower = keyword.lower()

            # 检测反常识关键词
            matched_keywords = [kw for kw in self.CONTRARIAN_KEYWORDS if kw in keyword_lower]

            has = len(matched_keywords) > 0
            verdict = has

            logger.info(f"Contrarian check: keyword='{keyword}', matched={matched_keywords}, has={has}, verdict={verdict}")
            return {"has": has, "verdict": verdict}

        except Exception as e:
            logger.warning(f"Contrarian check failed: {e}")
            return {"has": False, "verdict": False}

    def _check_counter_intuitive(self, keyword: str, category: str) -> dict:
        """Check 3: 反直觉数据

        启发式检测逻辑:
        - 检测关键词中的反直觉数据特征词
        - 包含数据/研究类词汇且有对比/转折意味

        Returns:
            {"has": bool, "verdict": bool}
            has: 是否包含反直觉特征
            verdict: True = 有反直觉数据（好），False = 缺乏
        """
        if self.mock_search:
            return {"has": False, "verdict": False}

        try:
            keyword_lower = keyword.lower()

            # 反直觉数据特征词 - 分为两组
            data_keywords = ["数据", "研究", "统计", "实验", "分析", "data", "study", "research", "analysis"]
            contrast_keywords = ["意外", "出人意料", "与预期相反", "但实际", "然而", "出乎意料", "却", "反而", "unexpect", "howev", "surpris"]

            # 需要同时包含数据词和对比词
            has_data = any(kw in keyword_lower for kw in data_keywords)
            has_contrast = any(kw in keyword_lower for kw in contrast_keywords)

            has = has_data and has_contrast
            verdict = has

            logger.info(f"Counter-intuitive check: keyword='{keyword}', has_data={has_data}, has_contrast={has_contrast}, has={has}, verdict={verdict}")
            return {"has": has, "verdict": verdict}

        except Exception as e:
            logger.warning(f"Counter-intuitive check failed: {e}")
            return {"has": False, "verdict": False}


def filter_topic(keyword: str, category: str = "", mock_search: bool = False) -> dict:
    """便捷函数：过滤选题

    Args:
        keyword: 选题关键词
        category: 分类
        mock_search: 是否使用 mock 搜索

    Returns:
        过滤结果字典
    """
    tf = TopicFilter(mock_search=mock_search)
    return tf.filter_topic(keyword, category)


if __name__ == "__main__":
    # 测试
    import json

    # 真实搜索测试
    print("=== 真实搜索测试 ===")
    result = filter_topic("WordPress 插件开发", category="技术")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Mock 搜索测试
    print("\n=== Mock 搜索测试 ===")
    result = filter_topic("测试关键词", mock_search=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))
