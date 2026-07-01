"""选题过滤器 - 多种门控机制

1. 三 Check 门控（原版）：
   - 近三月同质文章数量 - 启发式关键词评估
   - 反常识观点 - 争议性关键词检测
   - 反直觉数据 - 反直觉特征词检测

2. 五重过滤法（dbs-benchmark 启发）：
   - 有人搜吗：搜索结果数量和质量
   - 有痛点吗：是否解决实际问题
   - 有素材吗：是否有足够资料来源
   - 你能写吗：选题是否在能力范围内
   - 值得写吗：是否有差异化空间

源自 dontbesilent/dbskill 的对标分析哲学，改造为选题质量检测。
"""

import logging
import re
from dataclasses import dataclass
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


@dataclass
class BenchmarkFilterResult:
    """选题五重过滤结果"""
    passed: bool
    score: float  # 0-10
    filters: dict[str, bool]  # 5 个筛子的结果
    reasons: list[str]  # 未通过的原因
    suggestions: list[str]  # 改进建议


class BenchmarkTopicFilter:
    """选题五重过滤法 - dbs-benchmark 启发

    源自 dontbesilent/dbskill 的对标分析哲学，改造为选题质量检测。

    核心思想：
    - 务实过滤，不谈情怀
    - 能写就写，不能写就换下一个
    - 排除"我觉得""我喜欢"等主观噪音
    """

    # 痛点关键词
    PAIN_KEYWORDS = [
        "问题", "错误", "失败", "报错", "bug", "无法", "不能", "失败",
        "慢", "卡", "崩溃", "冲突", "异常", "警告",
        "怎么", "如何", "解决", "修复", "配置", "设置",
    ]

    # 素材类型信号
    MATERIAL_SIGNALS = {
        "教程": ["教程", "指南", "入门", "快速", "一步一步", "step by step"],
        "文档": ["文档", "document", "doc", "官方", "reference"],
        "案例": ["案例", "实例", "example", "实战", "实践"],
        "问答": ["问答", "question", "answer", "stack", "overflow", "知乎"],
    }

    # 过于宽泛的信号
    TOO_BROAD_KEYWORDS = [
        "是什么", "什么是", "简介", "概述", "介绍", "入门指南",
        "基础", "原理", "历史", "发展",
    ]

    # 过于深入的信号
    TOO_DEEP_KEYWORDS = [
        "源码分析", "内核", "底层实现", "架构设计",
        "深度", "原理", "剖析", "内幕",
    ]

    # 通用"如何"类模式
    HOW_TO_PATTERNS = ["如何", "怎么", "怎样", "how to"]

    # 技术限定词（可以拯救通用问题）
    TECH_QUALIFIERS = ["配置", "设置", "优化", "修复", "解决"]

    def __init__(self, search_results: list[dict] = None):
        """初始化过滤器

        Args:
            search_results: 搜索结果列表，格式：[{"title": str, "body": str}, ...]
        """
        self.search_results = search_results or []

    def filter_topic(self, keyword: str, category: str = "") -> BenchmarkFilterResult:
        """运行全部五重过滤

        Args:
            keyword: 选题关键词
            category: 分类（可选）

        Returns:
            BenchmarkFilterResult
        """
        self.keyword = keyword
        self.category = category

        filters = {
            "有人搜吗": self._check_search_volume(),
            "有痛点吗": self._check_pain_point(),
            "有素材吗": self._check_material_availability(),
            "你能写吗": self._check_writability(),
            "值得写吗": self._check_differentiation(),
        }

        # 计算评分
        passed_count = sum(filters.values())
        score = (passed_count / 5) * 10

        # 生成原因和建议
        reasons, suggestions = self._generate_reasons_and_suggestions(filters)

        # 通过标准：至少通过 4 个筛子
        passed = passed_count >= 4

        return BenchmarkFilterResult(
            passed=passed,
            score=round(score, 1),
            filters=filters,
            reasons=reasons,
            suggestions=suggestions
        )

    def _check_search_volume(self) -> bool:
        """筛子 1：有人搜吗？

        检测：搜索结果数量、质量、相关性

        相关性判断：至少有一个关键词组成部分出现在搜索结果中
        """
        if not self.search_results:
            return False

        # 首先检查搜索结果数量
        if len(self.search_results) < 5:
            return False

        # 提取关键词中的核心词（2字以上的中文或英文单词）
        keywords = re.findall(r'[a-zA-Z]{2,}|[一-龥]{2,}', self.keyword.lower())

        if not keywords:
            # 如果关键词太短，检查完整匹配
            kw_lower = self.keyword.lower()
            relevant_count = sum(
                1 for r in self.search_results[:10]
                if kw_lower in r.get("title", "").lower() or kw_lower in r.get("body", "").lower()
            )
            return relevant_count >= 3

        # 检查结果质量：核心词是否出现在标题或正文中
        relevant_count = 0
        for r in self.search_results[:10]:
            title = r.get("title", "").lower()
            snippet = r.get("body", "").lower()
            combined = title + " " + snippet

            # 至少有一个核心词出现在结果中
            if any(kw in combined for kw in keywords):
                relevant_count += 1

        return relevant_count >= 3

    def _check_pain_point(self) -> bool:
        """筛子 2：有痛点吗？

        检测：是否解决实际问题/错误/故障
        """
        if not self.search_results:
            return False

        pain_signals = 0
        for r in self.search_results[:5]:
            text = (r.get("title", "") + " " + r.get("body", "")).lower()
            for kw in self.PAIN_KEYWORDS:
                if kw in text:
                    pain_signals += 1
                    break

        return pain_signals >= 2

    def _check_material_availability(self) -> bool:
        """筛子 3：有素材吗？

        检测：是否有足够的资料来源（教程、文档、案例）
        """
        if not self.search_results:
            return False

        found_types: set[str] = set()
        for r in self.search_results[:10]:
            text = (r.get("title", "") + " " + r.get("body", "")).lower()
            for mtype, keywords in self.MATERIAL_SIGNALS.items():
                for kw in keywords:
                    if kw.lower() in text:
                        found_types.add(mtype)
                        break

        return len(found_types) >= 2

    def _check_writability(self) -> bool:
        """筛子 4：你能写吗？

        检测：选题是否在合理范围内（不过于宽泛/深入）
        """
        kw_lower = self.keyword.lower()

        # 检查是否过于宽泛 - 中文和英文分别处理
        for broad in self.TOO_BROAD_KEYWORDS:
            # 对于中文，直接包含检查
            if any('一' <= c <= '鿿' for c in broad):
                if broad in kw_lower:
                    return False
            else:
                # 对于英文，使用单词边界匹配
                pattern = r'\b' + re.escape(broad) + r'\b'
                if re.search(pattern, kw_lower):
                    return False

        # 检查是否过于深入
        for deep in self.TOO_DEEP_KEYWORDS:
            if deep in kw_lower:
                return False

        # 检查关键词长度
        if len(self.keyword) < 4:
            return False

        return True

    def _check_differentiation(self) -> bool:
        """筛子 5：值得写吗？

        检测：是否有差异化空间（是否已有大量同质内容）
        """
        if not self.search_results:
            return True  # 没有搜索结果时默认通过

        titles = [r.get("title", "") for r in self.search_results[:10]]
        titles = [t for t in titles if t]

        # 检查标题相似度
        if len(titles) >= 5:
            # 提取标题中的共同词（中文2字以上或英文3字母以上）
            common_words: set[str] = set()
            for t in titles[:5]:
                # 中文词（2字以上）
                cn_words = re.findall(r'[一-龥]{2,}', t)
                # 英文词（3字母以上）
                en_words = re.findall(r'[a-zA-Z]{3,}', t.lower())
                common_words.update(cn_words)
                common_words.update(en_words)

            # 如果某个词在半数以上标题中出现，说明同质严重
            for word in common_words:
                count = sum(1 for t in titles if word.lower() in t.lower())
                if count >= len(titles) / 2:
                    return False

        # 检查是否是"如何"类问题
        for pattern in self.HOW_TO_PATTERNS:
            if pattern in self.keyword.lower():
                # 但如果有技术限定词，仍然可以写
                if any(q in self.keyword for q in self.TECH_QUALIFIERS):
                    return True
                return False

        return True

    def _generate_reasons_and_suggestions(self, filters: dict[str, bool]) -> tuple[list[str], list[str]]:
        """生成原因和建议"""
        reasons: list[str] = []
        suggestions: list[str] = []

        filter_messages = {
            "有人搜吗": ("搜索结果为空或相关性低", "换个有关注度的选题，或缩小关键词范围"),
            "有痛点吗": ("没有明显的痛点信号", "调整选题方向，聚焦于问题/错误/故障"),
            "有素材吗": ("缺乏可用的写作素材", "先收集素材，或换个资料丰富的选题"),
            "你能写吗": ("选题过于宽泛或深入", "缩小选题范围，或增加技术限定词"),
            "值得写吗": ("已有大量同类内容", "添加具体场景/技术栈/限定条件，创造差异化"),
        }

        for fname, passed in filters.items():
            if not passed:
                reason, suggestion = filter_messages[fname]
                reasons.append(f"筛子: {fname} — {reason}")
                suggestions.append(suggestion)

        return reasons, suggestions

    def generate_report(self, keyword: str, category: str = "") -> str:
        """生成过滤报告"""
        result = self.filter_topic(keyword, category)

        lines = [
            f"# 选题过滤报告：{keyword}\n",
            f"**评分：{result.score}/10**",
            f"**结果：{'通过 ✅' if result.passed else '不通过 ❌'}**\n",
            "## 五重过滤结果\n",
            "| 筛子 | 结果 |",
            "|------|------|",
        ]

        for fname, passed in result.filters.items():
            status = "✅" if passed else "❌"
            lines.append(f"| {fname} | {status} |")

        if result.reasons:
            lines.append("\n## 未通过的原因\n")
            for reason in result.reasons:
                lines.append(f"- {reason}")

        if result.suggestions:
            lines.append("\n## 改进建议\n")
            for suggestion in result.suggestions:
                lines.append(f"- {suggestion}")

        return "\n".join(lines)


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
    import json

    # === 三 Check 门控测试 ===
    print("=== 三 Check 门控测试 ===")
    result = filter_topic("WordPress 插件开发", category="技术")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # === 五重过滤法测试 ===
    print("\n\n=== 五重过滤法测试 ===")

    test_results = [
        {"title": "Nginx 缓存配置教程", "body": "介绍如何配置 Nginx 缓存"},
        {"title": "Nginx proxy_cache 配置步骤", "body": "详细配置 proxy_cache"},
        {"title": "解决 Nginx 缓存不生效问题", "body": "排查缓存失败的原因"},
        {"title": "Nginx 缓存性能优化", "body": "提升缓存命中率的技巧"},
        {"title": "Nginx 配置错误导致缓存失败", "body": "常见错误排查"},
        {"title": "如何修复 Nginx 缓存错误", "body": "缓存问题排查指南"},
        {"title": "Nginx 缓存配置案例", "body": "实际配置示例"},
        {"title": "Nginx proxy_cache 官方文档", "body": "nginx.org proxy_cache 文档"},
        {"title": "Nginx 缓存问题 Stack Overflow", "body": "问答社区讨论"},
    ]

    bf = BenchmarkTopicFilter(search_results=test_results)

    print("\n--- 好选题测试 ---")
    print(bf.generate_report("Nginx 缓存配置错误修复"))

    print("\n\n--- 差选题测试 1（过于宽泛）---")
    # 用相同的搜索结果测试过于宽泛的选题
    print(bf.generate_report("什么是Nginx"))

    print("\n--- 差选题测试 2（无搜索结果）---")
    bf_empty = BenchmarkTopicFilter(search_results=[])
    print(bf_empty.generate_report("冷门小众技术入门指南"))

    print("\n--- 差选题测试 3（同质化严重）---")
    # 模拟同质化严重的搜索结果
    homogeneous_results = [
        {"title": "Python 教程", "body": "Python 入门教程"},
        {"title": "Python 快速入门", "body": "Python 快速上手指南"},
        {"title": "Python 基础教程", "body": "Python 基础知识"},
        {"title": "Python 从零开始", "body": "Python 新手指南"},
        {"title": "如何学习 Python", "body": "Python 学习方法"},
    ]
    bf_homo = BenchmarkTopicFilter(search_results=homogeneous_results)
    print(bf_homo.generate_report("Python 入门教程"))
