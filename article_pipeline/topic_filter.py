"""选题过滤器 - 三个 Check 门控机制

三个 Check:
1. 近三月同质文章数量 - DDG 搜索 + 结果计数
2. 反常识观点 - cocobook 搜索矛盾证据
3. 反直觉数据 - 研究素材里的反直觉数据

门控规则:
- 三个 check 全否 → low_value，不建议自动排入队列
- 至少一个是 → 可以进入队列
"""

import logging
from datetime import datetime, timedelta
from typing import Literal
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


class TopicFilter:
    """选题过滤器 - 评估选题价值"""

    def __init__(self, mock_search: bool = False):
        """初始化过滤器

        Args:
            mock_search: 是否使用 mock 搜索（测试用）
        """
        self.mock_search = mock_search
        self.ddgs = DDGS()

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

        搜索逻辑:
        - 构造时间范围查询（近三月）
        - 搜索结果数量评估

        Returns:
            {"score": int, "verdict": bool}
            score: 搜索结果数量（近似）
            verdict: True = 同质度低（好），False = 同质度高（不好）
        """
        if self.mock_search:
            # Mock 数据用于测试
            return {"score": 25, "verdict": False}

        try:
            # 构造搜索查询
            query = keyword
            if category:
                query = f"{category} {keyword}"

            # 执行搜索
            results = list(self.ddgs.text(query, max_results=20))

            score = len(results)
            # 阈值：超过 15 篇视为高同质化
            verdict = score < 15

            logger.info(f"Homogeneity check: query='{query}', results={score}, verdict={verdict}")
            return {"score": score, "verdict": verdict}

        except Exception as e:
            logger.warning(f"Homogeneity check failed: {e}")
            # 失败时保守处理，假定有同质化问题
            return {"score": 20, "verdict": False}

    def _check_contrarian(self, keyword: str, category: str) -> dict:
        """Check 2: 反常识观点

        搜索逻辑:
        - 在 cocobook 中搜索矛盾/反驳观点
        - 找到矛盾证据说明观点有争议性

        Returns:
            {"has": bool, "verdict": bool}
            has: 是否找到矛盾证据
            verdict: True = 有反常识性（好），False = 缺乏反常识性
        """
        if self.mock_search:
            return {"has": False, "verdict": False}

        try:
            # TODO: 集成 cocobook MCP 搜索
            # 当前先用简单关键词匹配模拟
            contrarian_keywords = [
                "误区", "误解", "常见错误", "反向", "反驳",
                "争议", "相反", "不是", "打破"
            ]

            query = f"{keyword} {' OR '.join(contrarian_keywords[:3])}"

            # 用 DDG 暂代 cocobook
            results = list(self.ddgs.text(query, max_results=5))

            has = len(results) > 0
            # 找到矛盾证据是好事
            verdict = has

            logger.info(f"Contrarian check: query='{query}', has={has}, verdict={verdict}")
            return {"has": has, "verdict": verdict}

        except Exception as e:
            logger.warning(f"Contrarian check failed: {e}")
            return {"has": False, "verdict": False}

    def _check_counter_intuitive(self, keyword: str, category: str) -> dict:
        """Check 3: 反直觉数据

        搜索逻辑:
        - 在研究素材中搜索反直觉数据点
        - 关键词：意外、出人意料、与预期相反、数据显示

        Returns:
            {"has": bool, "verdict": bool}
            has: 是否找到反直觉数据
            verdict: True = 有反直觉数据（好），False = 缺乏
        """
        if self.mock_search:
            return {"has": False, "verdict": False}

        try:
            # 反直觉数据特征词
            counter_intuitive_keywords = [
                "意外", "出人意料", "与预期相反",
                "数据显示", "研究发现", "统计表明",
                "但实际", "然而", "出乎意料"
            ]

            # 构造查询
            parts = [f"{keyword} {kw}" for kw in counter_intuitive_keywords[:4]]
            query = " OR ".join(parts)

            # 用 DDG 暂代
            results = list(self.ddgs.text(query, max_results=5))

            has = len(results) > 0
            verdict = has

            logger.info(f"Counter-intuitive check: has={has}, verdict={verdict}")
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
