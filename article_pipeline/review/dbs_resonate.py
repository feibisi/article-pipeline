"""文稿共鸣诊断 — dbs-resonate 启发

源自 dontbesilent/dbskill 的传播心理学框架，改造为文稿质量检测。

5 个维度（传播学经典理论）：
1. 沉默的螺旋（诺依曼，1974）— 是否说出受众憋着不敢说的话
2. 使用与满足理论（卡茨，1959）— 满足什么心理需求
3. 框架理论（恩特曼，1993）— 站在谁那边
4. 两级传播理论（拉扎斯菲尔德，1944）— 谁会第一个传播
5. 认知一致性理论（费斯廷格，1957）— 确认什么信念，触发行动冲动

核心哲学：
- 共鸣是结构性的，不是运气
- 全面不等于专业，精准才等于专业
- 情绪优先于信息，立场决定接受度
"""

import dataclasses
import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class ResonanceDimension:
    """单个共鸣维度的检测结果"""
    name: str
    status: Literal["有效", "弱", "无效"]
    reason: str
    evidence: list[str]  # 文稿中的具体证据


@dataclass
class ResonanceReport:
    """共鸣诊断报告"""
    overall_score: float  # 0-10
    core_mechanism: str  # 核心机制是什么
    status: Literal["有效", "弱", "无效"]
    dimensions: list[ResonanceDimension]
    suggestions: list[str]


class ResonanceChecker:
    """文稿共鸣诊断器"""

    # 沉默解除信号 - 受众憋着的话
    SILENCE_BREAKING_SIGNALS = [
        "终于", "总算", "一直以来", "憋在心里", "不好意思说",
        "没人告诉过你", "很少有人提", "大家都", "明知道",
        "其实", "坦白说", "说白了", "不瞒你说",
    ]

    # 满足动机类型关键词
    FULFILLMENT_PATTERNS = {
        "身份认同": ["我们是", "我们是这类人", "像我们这样的", "共同经历"],
        "情绪宣泄": ["终于可以", "终于不用", "烦死了", "受够了", "受不了"],
        "社交资本": ["转发", "告诉朋友", "分享给", "值得收藏"],
        "信息价值": ["不知道", "很少有人知道", "第一次公开", "揭秘"],
    }

    # 立场框架信号
    STANCE_SIGNALS = {
        "服务者立场": ["我们", "咱们", "我遇到过", "我的经验", "我试过"],
        "教育者立场": ["你应该", "你必须", "大家要", "记住", "学会"],
        "分析者立场": ["数据显示", "研究证明", "实验表明", "分析发现"],
        "批判者立场": ["问题在于", "错误是", "不应该", "误区", "陷阱"],
    }

    # 传播入口信号 - 谁会第一个传播
    SPREADER_SIGNALS = {
        "同行": ["同事", "团队", "项目", "开发", "工作"],
        "学习者": ["初学者", "入门", "新手", "刚接触", "学习"],
        "决策者": ["选择", "决定", "评估", "选型", "方案"],
    }

    # 信念结构信号
    BELIEF_CONFIRMATION = [
        "一直以为", "原以为", "以前觉得", "以前认为",
    ]

    # 行动冲动信号
    ACTION_IMPELLING = [
        "现在就可以", "今天就能", "只需", "只需要",
        "试试", "试一下", "不妨", "可以尝试",
    ]

    def __init__(self):
        """初始化共鸣诊断器"""
        pass

    def check_draft(self, draft: str, category: str = "") -> ResonanceReport:
        """诊断文稿共鸣

        Args:
            draft: 文稿内容
            category: 分类（可选，用于调整检测阈值）

        Returns:
            ResonanceReport
        """
        if not draft or len(draft) < 100:
            return self._empty_report()

        # 提取所有主张/观点
        claims = self._extract_claims(draft)

        # 找核心机制
        core_mechanism = self._find_core_mechanism(draft, claims)

        # 5 维度检测
        dimensions = [
            self._check_silence_breaking(draft),
            self._check_fulfillment(draft),
            self._check_stance(draft),
            self._check_spreader(draft),
            self._check_belief_action(draft),
        ]

        # 计算总分
        status_count = {"有效": 0, "弱": 0, "无效": 0}
        for dim in dimensions:
            status_count[dim.status] += 1

        # 评分逻辑
        # 有效数量 >= 3 → 8-10分
        # 有效数量 >= 2 且无无效 → 6-7分
        # 有效数量 >= 1 且无效 <= 2 → 4-5分
        # 否则 → 0-3分
        effective = status_count["有效"]
        weak = status_count["弱"]
        invalid = status_count["无效"]

        if effective >= 3:
            overall_score = 8.0 + (effective - 3) * 0.5
            status = "有效"
        elif effective >= 2 and invalid == 0:
            overall_score = 6.0 + weak * 0.5
            status = "有效"
        elif effective >= 1 and invalid <= 2:
            overall_score = 4.0 + effective * 0.5
            status = "弱"
        else:
            overall_score = 2.0 + effective
            status = "无效"

        overall_score = min(10.0, overall_score)

        # 生成建议
        suggestions = self._generate_suggestions(dimensions, claims)

        return ResonanceReport(
            overall_score=round(overall_score, 1),
            core_mechanism=core_mechanism,
            status=status,
            dimensions=dimensions,
            suggestions=suggestions
        )

    def _empty_report(self) -> ResonanceReport:
        """空文稿报告"""
        return ResonanceReport(
            overall_score=0.0,
            core_mechanism="文稿为空或过短，无法诊断",
            status="无效",
            dimensions=[],
            suggestions=["文稿内容过少，无法进行共鸣诊断"]
        )

    def _extract_claims(self, draft: str) -> list[str]:
        """提取文稿中的所有主张/观点

        简化版：按段落提取，过滤掉太短的
        """
        paragraphs = draft.split("\n\n")
        claims = []
        for p in paragraphs:
            p = p.strip()
            if len(p) >= 20 and not p.startswith("#"):
                # 去掉 markdown 格式
                p_clean = re.sub(r'[**#`\[\]]', '', p)
                if p_clean:
                    claims.append(p_clean[:100])  # 截取前100字作为主张摘要
        return claims[:10]  # 最多取10个主张

    def _find_core_mechanism(self, draft: str, claims: list[str]) -> str:
        """找出核心机制

        简化版：返回第一个重要段落的主张
        """
        if not claims:
            return "无法识别核心机制"

        # 检查是否有明确的论点声明
        for claim in claims:
            if any(word in claim for word in ["核心", "关键", "本质", "真正", "其实"]):
                return claim[:50] + "..." if len(claim) > 50 else claim

        # 默认返回第一个主张
        first_claim = claims[0]
        return first_claim[:50] + "..." if len(first_claim) > 50 else first_claim

    def _check_silence_breaking(self, draft: str) -> ResonanceDimension:
        """维度1：沉默解除（沉默的螺旋）

        检测是否说出受众憋着不敢说的话
        """
        draft_lower = draft.lower()

        matched = []
        for signal in self.SILENCE_BREAKING_SIGNALS:
            if signal in draft_lower:
                matched.append(signal)

        if len(matched) >= 2:
            status = "有效"
            reason = f"发现 {len(matched)} 处沉默解除信号"
        elif len(matched) >= 1:
            status = "弱"
            reason = f"仅发现 1 处沉默解除信号"
        else:
            status = "无效"
            reason = "没有沉默解除信号，内容可能过于平淡"

        return ResonanceDimension(
            name="沉默解除",
            status=status,
            reason=reason,
            evidence=matched[:3]
        )

    def _check_fulfillment(self, draft: str) -> ResonanceDimension:
        """维度2：满足动机（使用与满足理论）

        检测满足的是什么心理需求
        """
        draft_lower = draft.lower()

        matched_types = []
        for ftype, patterns in self.FULFILLMENT_PATTERNS.items():
            if any(p in draft_lower for p in patterns):
                matched_types.append(ftype)

        if len(matched_types) >= 2:
            status = "有效"
            reason = f"满足多种需求：{', '.join(matched_types)}"
        elif len(matched_types) == 1:
            status = "弱"
            reason = f"仅满足单一需求：{matched_types[0]}"
        else:
            status = "无效"
            reason = "没有明确的心理满足动机"

        return ResonanceDimension(
            name="满足动机",
            status=status,
            reason=reason,
            evidence=matched_types
        )

    def _check_stance(self, draft: str) -> ResonanceDimension:
        """维度3：立场框架（框架理论）

        检测内容站在谁那边
        """
        draft_lower = draft.lower()

        matched_stances = []
        for stance, patterns in self.STANCE_SIGNALS.items():
            if any(p in draft_lower for p in patterns):
                matched_stances.append(stance)

        # 评估立场一致性
        if len(matched_stances) == 0:
            status = "无效"
            reason = "立场不明确，受众不知道站在谁那边"
        elif len(matched_stances) == 1:
            status = "有效"
            reason = f"立场明确：{matched_stances[0]}"
        elif len(matched_stances) >= 3:
            status = "无效"
            reason = f"立场混乱，同时切换了 {len(matched_stances)} 种立场"
        else:
            status = "弱"
            reason = f"立场有一定漂移：{', '.join(matched_stances)}"

        return ResonanceDimension(
            name="立场框架",
            status=status,
            reason=reason,
            evidence=matched_stances
        )

    def _check_spreader(self, draft: str) -> ResonanceDimension:
        """维度4：传播入口（两级传播理论）

        检测谁会第一个传播这条内容
        """
        draft_lower = draft.lower()

        matched_groups = []
        for group, patterns in self.SPREADER_SIGNALS.items():
            if any(p in draft_lower for p in patterns):
                matched_groups.append(group)

        if len(matched_groups) >= 1:
            status = "有效"
            reason = f"目标群体明确：{', '.join(matched_groups)}"
        else:
            status = "弱"
            reason = "目标群体不明确，难以触发传播"

        return ResonanceDimension(
            name="传播入口",
            status=status,
            reason=reason,
            evidence=matched_groups
        )

    def _check_belief_action(self, draft: str) -> ResonanceDimension:
        """维度5：信念结构（认知一致性理论）

        检测确认了什么信念，是否触发行动冲动
        """
        draft_lower = draft.lower()

        # 检查信念确认
        belief_confirmed = any(p in draft_lower for p in self.BELIEF_CONFIRMATION)

        # 检查行动冲动
        action_triggered = any(p in draft_lower for p in self.ACTION_IMPELLING)

        evidence = []
        if belief_confirmed:
            evidence.append("信念确认")
        if action_triggered:
            evidence.append("行动冲动")

        if belief_confirmed and action_triggered:
            status = "有效"
            reason = "既有信念确认，又有行动冲动，传播潜力高"
        elif belief_confirmed or action_triggered:
            status = "弱"
            reason = "仅有信念确认或行动冲动之一"
        else:
            status = "无效"
            reason = "没有信念确认，也没有行动冲动"

        return ResonanceDimension(
            name="信念结构",
            status=status,
            reason=reason,
            evidence=evidence
        )

    def _generate_suggestions(self, dimensions: list[ResonanceDimension], claims: list[str]) -> list[str]:
        """生成改进建议"""
        suggestions = []

        for dim in dimensions:
            if dim.status == "无效":
                if dim.name == "沉默解除":
                    suggestions.append("添加受众憋着不敢说的话，如'终于''终于可以''一直以来'")
                elif dim.name == "满足动机":
                    suggestions.append("明确受众看完后满足了什么心理需求（身份认同/情绪宣泄/社交资本/信息价值）")
                elif dim.name == "立场框架":
                    suggestions.append("统一立场，从头到尾站在同一类人那边，不要漂移")
                elif dim.name == "传播入口":
                    suggestions.append("明确目标群体，让第一批传播者知道自己为什么要分享")
                elif dim.name == "信念结构":
                    suggestions.append("添加信念确认或行动冲动，让受众看完有想做的冲动")
            elif dim.status == "弱":
                if dim.name == "沉默解除":
                    suggestions.append("加强沉默解除信号，多使用'终于''其实''说白了'等词")
                elif dim.name == "满足动机":
                    suggestions.append("强化心理满足动机，可以同时满足多种需求")
                elif dim.name == "立场框架":
                    suggestions.append("检查立场是否一致，避免在不同段落间切换立场")
                elif dim.name == "信念结构":
                    suggestions.append("补充信念确认或行动冲动环节")

        return suggestions

    def generate_report(self, draft: str, category: str = "") -> str:
        """生成共鸣诊断报告

        Args:
            draft: 文稿内容
            category: 分类

        Returns:
            Markdown 格式的报告
        """
        result = self.check_draft(draft, category)

        lines = [
            f"# 文稿共鸣诊断\n",
            f"**评分：{result.overall_score}/10**",
            f"**结果：{result.status}**\n",
            f"**核心机制：** {result.core_mechanism}\n",
            "## 五维度诊断\n",
            "| 维度 | 状态 | 说明 |",
            "|------|------|------|",
        ]

        for dim in result.dimensions:
            status_icon = {"有效": "✅", "弱": "⚠️", "无效": "❌"}[dim.status]
            evidence_str = ", ".join(dim.evidence) if dim.evidence else "-"
            lines.append(f"| {dim.name} | {status_icon} {dim.status} | {dim.reason} |")

        if result.suggestions:
            lines.append("\n## 改进建议\n")
            for suggestion in result.suggestions:
                lines.append(f"- {suggestion}")

        return "\n".join(lines)


# 便捷函数
def check_resonance(draft: str, category: str = "") -> ResonanceReport:
    """检查文稿共鸣

    Args:
        draft: 文稿内容
        category: 分类

    Returns:
        ResonanceReport
    """
    checker = ResonanceChecker()
    return checker.check_draft(draft, category)


def generate_resonance_report(draft: str, category: str = "") -> str:
    """生成共鸣诊断报告

    Args:
        draft: 文稿内容
        category: 分类

    Returns:
        Markdown 格式的报告
    """
    checker = ResonanceChecker()
    return checker.generate_report(draft, category)


if __name__ == "__main__":
    # 测试
    good_draft = """
# Nginx 缓存配置终于能正常工作了

一直以来，Nginx 的 proxy_cache 配置都很让人头疼。
我终于找到了问题所在。

其实问题很简单，就是 proxy_cache_path 和 proxy_cache
没有正确对应。

我们经常会遇到这种情况：配置写了一大堆，
但缓存就是不生效。烦死了。

现在只需把这两行改成这样：

```
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m;
proxy_cache my_cache;
```

试试看，今天就能解决问题。
"""

    print("=== 好文稿测试 ===")
    print(generate_resonance_report(good_draft))

    print("\n\n=== 差文稿测试 ===")
    bad_draft = """
# Nginx 缓存配置

Nginx 是一个高性能的 Web 服务器。
它支持缓存功能。

缓存可以提高性能。
配置缓存需要使用 proxy_cache 指令。
"""

    print(generate_resonance_report(bad_draft))
