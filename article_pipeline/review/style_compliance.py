"""Style Compliance Checker — 检查文章是否遵循了风格指令

5 维度检测：
1. warmth → 人称使用频率（"你"/"我们"/第三人称）
2. density → 段落平均长度分布
3. energy → 短句/长句比例、反问句频率
4. edge → 判断句位置（是否前置）、确定性词汇密度
5. register → 口语词/书面词比例
"""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class ComplianceDimension:
    """单个维度的合规性检测结果"""
    name: str
    score: float  # 0-10
    status: Literal["通过", "警告", "不通过"]
    details: str
    evidence: dict[str, float]  # 具体指标数据


@dataclass
class ComplianceReport:
    """风格合规性报告"""
    overall_score: float  # 0-10
    dimensions: list[ComplianceDimension]
    suggestions: list[str]


class StyleComplianceChecker:
    """风格合规性检测器"""

    # 人称关键词
    PERSONAL_PRONOUNS = {
        "second_person": ["你", "您的", "你们", "咱们"],
        "first_person_plural": ["我们", "咱们"],
        "third_person": ["他", "她", "它", "他们", "它们", "读者", "用户"],
    }

    # 确定性词汇（高 edge）
    CERTAINTY_WORDS = [
        "必须", "一定要", "绝对", "肯定", "必然",
        "无疑", "显然", "明显", "确实", "的确",
    ]

    # 委态词汇（低 edge）
    HEDGING_WORDS = [
        "可能", "或许", "大概", "也许", "似乎",
        "通常", "一般", "往往", "基本", "差不多",
    ]

    # 反问句模式
    RHETORICAL_PATTERNS = [
        r".*吗\?", r".*么\?", r".*呢\?", r"难道.*\?",
    ]

    # 口语词（高 register 负相关）
    COLLOQUIAL_WORDS = [
        "啥", "咋", "嗯", "哦", "啊", "嘛",
        "挺", "蛮", "特", "超", "巨",
    ]

    # 书面词（高 register 正相关）
    FORMAL_WORDS = [
        "因此", "然而", "此外", "再者", "综上所述",
        "换言之", "具体而言", "实质上", "本质上",
    ]

    def __init__(self):
        """初始化检测器"""
        pass

    def check_compliance(
        self,
        article: str,
        style_vector: dict | None = None
    ) -> ComplianceReport:
        """检查文章风格合规性

        Args:
            article: 文章内容
            style_vector: 风格向量（可选，用于调整阈值）

        Returns:
            ComplianceReport
        """
        if not article or len(article) < 100:
            return self._empty_report()

        # 5 维度检测
        dimensions = [
            self._check_warmth(article),
            self._check_density(article),
            self._check_energy(article),
            self._check_edge(article),
            self._check_register(article),
        ]

        # 计算总分
        overall = sum(d.score for d in dimensions) / len(dimensions)

        # 生成建议
        suggestions = self._generate_suggestions(dimensions)

        return ComplianceReport(
            overall_score=round(overall, 1),
            dimensions=dimensions,
            suggestions=suggestions
        )

    def _empty_report(self) -> ComplianceReport:
        """空文章报告"""
        return ComplianceReport(
            overall_score=0.0,
            dimensions=[],
            suggestions=["文章内容过少，无法进行风格合规性检测"]
        )

    def _check_warmth(self, article: str) -> ComplianceDimension:
        """维度1：warmth — 人称使用频率

        检测：
        - 第二人称（你）使用频率
        - 第一人称复数（我们）使用频率
        - 第三人称使用频率

        高 warmth 应该多使用"你"和"我们"
        """
        article_lower = article.lower()

        second_count = sum(1 for word in self.PERSONAL_PRONOUNS["second_person"] if word in article_lower)
        first_pl_count = sum(1 for word in self.PERSONAL_PRONOUNS["first_person_plural"] if word in article_lower)
        third_count = sum(1 for word in self.PERSONAL_PRONOUNS["third_person"] if word in article_lower)

        total_chars = len(article)
        # 每 1000 字中的出现频率
        second_freq = (second_count / total_chars * 1000) if total_chars > 0 else 0
        first_pl_freq = (first_pl_count / total_chars * 1000) if total_chars > 0 else 0

        # 评分逻辑
        # 第二人称 >= 5次/千字 → 高分
        # 第一人称复数 >= 3次/千字 → 加分
        if second_freq >= 5:
            score = 8.0 + min(2.0, second_freq - 5)
        elif second_freq >= 2:
            score = 5.0 + (second_freq - 2) * 1.5
        else:
            score = 3.0 + second_freq

        score = min(10.0, score)

        if score >= 7.0:
            status = "通过"
        elif score >= 4.0:
            status = "警告"
        else:
            status = "不通过"

        details = f"第二人称 {second_count} 次 ({second_freq:.1f}/千字)，第一人称复数 {first_pl_count} 次"

        return ComplianceDimension(
            name="warmth",
            score=round(score, 1),
            status=status,
            details=details,
            evidence={
                "second_person_count": second_count,
                "first_plural_count": first_pl_count,
                "third_person_count": third_count,
            }
        )

    def _check_density(self, article: str) -> ComplianceDimension:
        """维度2：density — 段落长度分布

        检测：
        - 段落数量
        - 平均段落长度（字数）
        - 长段落（>200字）占比

        高 density 应该段落较长，信息密度高
        低 density 应该段落较短，更易读
        """
        paragraphs = [p for p in article.split("\n\n") if len(p.strip()) > 10]

        if not paragraphs:
            return ComplianceDimension(
                name="density",
                score=0.0,
                status="不通过",
                details="没有有效段落",
                evidence={}
            )

        para_lengths = [len(re.sub(r'[ \t\n]', '', p)) for p in paragraphs]
        avg_length = sum(para_lengths) / len(para_lengths)
        long_paras = sum(1 for l in para_lengths if l > 200)
        long_para_ratio = (long_paras / len(para_lengths)) if para_lengths else 0

        # 评分逻辑（假设中等密度为佳）
        # 平均段落长度 100-200 字 → 高分
        if 100 <= avg_length <= 200:
            score = 8.0
        elif 50 <= avg_length < 100 or 200 < avg_length <= 300:
            score = 6.0
        else:
            score = 4.0

        # 长段落过多扣分
        if long_para_ratio > 0.5:
            score -= 2.0

        score = max(0.0, min(10.0, score))

        if score >= 7.0:
            status = "通过"
        elif score >= 4.0:
            status = "警告"
        else:
            status = "不通过"

        details = f"共 {len(para_lengths)} 段，平均 {avg_length:.0f} 字，长段落占 {long_para_ratio:.0%}"

        return ComplianceDimension(
            name="density",
            score=round(score, 1),
            status=status,
            details=details,
            evidence={
                "paragraph_count": len(para_lengths),
                "avg_length": round(avg_length, 1),
                "long_para_ratio": round(long_para_ratio, 2),
            }
        )

    def _check_energy(self, article: str) -> ComplianceDimension:
        """维度3：energy — 节奏感

        检测：
        - 短句（<15字）比例
        - 反问句数量
        - 句长方差（节奏变化）

        高 energy 应该有更多短句和反问
        """
        # 分句（按句号、问号、感叹号）
        sentences = re.split(r'[。！？\?]', article)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

        if not sentences:
            return ComplianceDimension(
                name="energy",
                score=0.0,
                status="不通过",
                details="没有有效句子",
                evidence={}
            )

        sentence_lengths = [len(s) for s in sentences]
        avg_length = sum(sentence_lengths) / len(sentence_lengths)
        short_sentences = sum(1 for l in sentence_lengths if l < 15)
        short_ratio = (short_sentences / len(sentence_lengths)) if sentence_lengths else 0

        # 反问句检测
        rhetorical_count = 0
        for pattern in self.RHETORICAL_PATTERNS:
            rhetorical_count += len(re.findall(pattern, article))

        rhetorical_freq = (rhetorical_count / len(sentence_lengths)) if sentence_lengths else 0

        # 评分逻辑
        # 短句比例 20-40% → 高分
        if 0.2 <= short_ratio <= 0.4:
            score = 7.0
        elif 0.1 <= short_ratio < 0.2 or 0.4 < short_ratio <= 0.5:
            score = 5.0
        else:
            score = 3.0

        # 有反问句加分
        if rhetorical_count > 0:
            score += min(2.0, rhetorical_count * 0.5)

        score = max(0.0, min(10.0, score))

        if score >= 7.0:
            status = "通过"
        elif score >= 4.0:
            status = "警告"
        else:
            status = "不通过"

        details = f"短句占 {short_ratio:.0%}，反问句 {rhetorical_count} 个"

        return ComplianceDimension(
            name="energy",
            score=round(score, 1),
            status=status,
            details=details,
            evidence={
                "sentence_count": len(sentence_lengths),
                "avg_sentence_length": round(avg_length, 1),
                "short_sentence_ratio": round(short_ratio, 2),
                "rhetorical_count": rhetorical_count,
            }
        )

    def _check_edge(self, article: str) -> ComplianceDimension:
        """维度4：edge — 立场强度

        检测：
        - 确定性词汇密度
        - 委态词汇密度
        - 判断句（有明确立场的句子）比例

        高 edge 应该多使用确定性词汇，少用委态词汇
        """
        article_lower = article.lower()

        certainty_count = sum(1 for word in self.CERTAINTY_WORDS if word in article_lower)
        hedging_count = sum(1 for word in self.HEDGING_WORDS if word in article_lower)

        total_chars = len(article)
        certainty_freq = (certainty_count / total_chars * 1000) if total_chars > 0 else 0
        hedging_freq = (hedging_count / total_chars * 1000) if total_chars > 0 else 0

        # 判断句检测（包含明确判断词的句子）
        judgment_patterns = [
            r'.*是.*的.*', r'.*应该.*', r'.*必须.*',
            r'.*最好.*', r'.*不要.*', r'.*可以.*'
        ]
        judgment_count = sum(len(re.findall(p, article_lower)) for p in judgment_patterns)

        # 评分逻辑
        # 确定性/委态比例 > 1 → 高分
        ratio = certainty_count / (hedging_count + 1)  # +1 避免除零

        if ratio > 1.0:
            score = 7.0 + min(3.0, ratio)
        elif ratio > 0.5:
            score = 5.0
        else:
            score = 3.0

        # 有判断句加分
        if judgment_count > 0:
            score += min(2.0, judgment_count * 0.1)

        score = max(0.0, min(10.0, score))

        if score >= 7.0:
            status = "通过"
        elif score >= 4.0:
            status = "警告"
        else:
            status = "不通过"

        details = f"确定性词 {certainty_count} 次，委态词 {hedging_count} 次，比例 {ratio:.1f}"

        return ComplianceDimension(
            name="edge",
            score=round(score, 1),
            status=status,
            details=details,
            evidence={
                "certainty_count": certainty_count,
                "hedging_count": hedging_count,
                "certainty_hedging_ratio": round(ratio, 2),
            }
        )

    def _check_register(self, article: str) -> ComplianceDimension:
        """维度5：register — 语域

        检测：
        - 口语词使用频率
        - 书面词使用频率
        - 口语/书面词比例

        高 register 应该多用书面词，少用口语词
        低 register 可以用口语词
        """
        article_lower = article.lower()

        colloquial_count = sum(1 for word in self.COLLOQUIAL_WORDS if word in article_lower)
        formal_count = sum(1 for word in self.FORMAL_WORDS if word in article_lower)

        total_chars = len(article)
        colloquial_freq = (colloquial_count / total_chars * 1000) if total_chars > 0 else 0
        formal_freq = (formal_count / total_chars * 1000) if total_chars > 0 else 0

        # 评分逻辑
        # 书面词多于口语词 → 高分
        ratio = formal_count / (colloquial_count + 1)  # +1 避免除零

        if ratio > 2.0:
            score = 8.0 + min(2.0, (ratio - 2.0) * 0.5)
        elif ratio > 1.0:
            score = 6.0 + (ratio - 1.0) * 2.0
        elif ratio > 0.5:
            score = 4.0
        else:
            score = 2.0

        score = max(0.0, min(10.0, score))

        if score >= 7.0:
            status = "通过"
        elif score >= 4.0:
            status = "警告"
        else:
            status = "不通过"

        details = f"书面词 {formal_count} 次，口语词 {colloquial_count} 次，比例 {ratio:.1f}"

        return ComplianceDimension(
            name="register",
            score=round(score, 1),
            status=status,
            details=details,
            evidence={
                "formal_count": formal_count,
                "colloquial_count": colloquial_count,
                "formal_colloquial_ratio": round(ratio, 2),
            }
        )

    def _generate_suggestions(self, dimensions: list[ComplianceDimension]) -> list[str]:
        """生成改进建议"""
        suggestions = []

        for dim in dimensions:
            if dim.status == "不通过":
                if dim.name == "warmth":
                    suggestions.append("增加第二人称（你）的使用频率，拉近与读者距离")
                elif dim.name == "density":
                    suggestions.append("调整段落长度，保持 100-200 字/段的最佳密度")
                elif dim.name == "energy":
                    suggestions.append("增加短句比例（20-40%），或使用反问句增强节奏感")
                elif dim.name == "edge":
                    suggestions.append("减少委态词汇（可能、或许），增加确定性表达")
                elif dim.name == "register":
                    suggestions.append("减少口语词，增加书面连接词（因此、然而、此外）")
            elif dim.status == "警告":
                if dim.name == "warmth":
                    suggestions.append("适当增加第二人称使用")
                elif dim.name == "density":
                    suggestions.append("优化段落长度分布")
                elif dim.name == "energy":
                    suggestions.append("调整句长节奏，增加变化")
                elif dim.name == "edge":
                    suggestions.append("平衡确定性与委态表达")
                elif dim.name == "register":
                    suggestions.append("调整口语词和书面词比例")

        return suggestions


def check_style_compliance(article: str, style_vector: dict | None = None) -> ComplianceReport:
    """检查文章风格合规性

    Args:
        article: 文章内容
        style_vector: 风格向量（可选）

    Returns:
        ComplianceReport
    """
    checker = StyleComplianceChecker()
    return checker.check_compliance(article, style_vector)


def generate_compliance_report(article: str, style_vector: dict | None = None) -> str:
    """生成风格合规性报告

    Args:
        article: 文章内容
        style_vector: 风格向量（可选）

    Returns:
        Markdown 格式的报告
    """
    checker = StyleComplianceChecker()
    result = checker.check_compliance(article, style_vector)

    lines = [
        "# 风格合规性检测报告\n",
        f"**总分：{result.overall_score}/10**\n",
        "## 五维度检测结果\n",
        "| 维度 | 得分 | 状态 | 详情 |",
        "|------|------|------|------|",
    ]

    for dim in result.dimensions:
        status_icon = {"通过": "✅", "警告": "⚠️", "不通过": "❌"}[dim.status]
        lines.append(f"| {dim.name} | {dim.score} | {status_icon} {dim.status} | {dim.details} |")

    if result.suggestions:
        lines.append("\n## 改进建议\n")
        for suggestion in result.suggestions:
            lines.append(f"- {suggestion}")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    test_article = """
# Nginx 缓存配置教程

你是否遇到过这样的问题：Nginx 缓存配置写了一大堆，
但就是不生效？本文告诉你解决方案。

## 为什么缓存不生效

原因其实很简单。你的配置可能有问题。

必须检查 proxy_cache_path 和 proxy_cache 是否对应。

## 如何解决

你应该按照以下步骤操作：

1. 检查配置文件
2. 重启 Nginx
3. 验证结果

因此，正确的做法是仔细检查每一个配置项。
"""

    print("=== 风格合规性检测 ===")
    print(generate_compliance_report(test_article))
