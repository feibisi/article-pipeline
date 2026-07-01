# Article Pipeline 级联编译类型化契约

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "SynthesisOutput",
    "FrameworkOutput",
    "StyleOutput",
    "ProsodyOutput",
    "CompileOutput",
    "HeroBrief",
    "VisualAnchor",
    "SeoMetadata",
]


@dataclass
class SynthesisOutput:
    """Layer 1 -> Layer 2 的类型化契约

    综合分析层的输出，定义文章的核心理解和证据基础。
    """
    core_judgment: str  # 一句话：这篇文章要传递什么理解
    evidence_for: list[dict]  # [{source, claim, strength}]
    evidence_against: list[dict]
    conflicts: list[dict]  # [{source_a, source_b, claim_a, claim_b, resolution}]
    unique_claims: list[str]  # DDG 前 10 结果中找不到的 claim
    differentiation: str  # 比搜索第一页多给读者什么（生成于 synthesis，门控在 outline 阶段验证）
    confidence: float  # 0-1，synthesis 对自己判断的信心
    freeform_note: str = ""  # 字段装不下但重要的微妙信息（语气转折、潜台词、节奏呼吸感）


@dataclass
class FrameworkOutput:
    """Layer 2 -> Layer 5 的类型化契约

    框架设计层的输出，定义文章的结构和方法论。
    """
    method: str  # 使用的方法论名（e.g. "steel_man_refutation"）
    structure: list[dict]  # [{role, h2_title, purpose, evidence_ids, word_budget}]
    takeaway: str  # 一句话卖点
    reader_entry_state: str  # 读者进来时认为什么（要被翻转或确认的）
    reader_exit_state: str  # 读者出去时应该理解什么
    visual_anchors: list[dict] | None = None  # [{section_role, concept, visual_type, screenshot_target?, diagram_spec?}]
    # visual_anchors 设计意图: Phase 5 素材集成时激活，当前阶段为 None
    freeform_note: str = ""  # 字段装不下但重要的微妙信息（语气转折、潜台词、节奏呼吸感）


@dataclass
class StyleOutput:
    """Layer 3 -> Layer 5 的类型化契约

    风格定义层的输出，定义文章的语言风格和约束。
    """
    vector: dict  # 5 维坐标值 {density, warmth, energy, register, edge}
    constraints: dict  # {require: [...], allow: [...], avoid: [...]}
    rendered_instructions: str  # 人类可读的风格指令文本（给 LLM 参考）
    aesthetic_concepts: list[str]  # 适用的审美概念子集
    freeform_note: str = ""  # 字段装不下但重要的微妙信息（语气转折、潜台词、节奏呼吸感）


@dataclass
class ProsodyOutput:
    """Layer 4 -> Layer 5 的类型化契约

    语感引导层的输出，提供创作范本和节奏指导。
    创作层允许偏离范本，不做强制合规检查。
    """
    samples: list[str]  # 2-3 个语感范本段落
    sample_type: str  # 范本类型（short_push / flowing / staccato / ...）
    negative_constraints: str  # 硬性禁止列表
    rhythm_hint: str  # 一句话节奏提示（e.g. "短句密集推进，长句仅在总结时出现"）
    freeform_note: str = ""  # 字段装不下但重要的微妙信息（语气转折、潜台词、节奏呼吸感）


@dataclass
class HeroBrief:
    """封面图需求描述（T-016 结构化输出）"""
    concept: str  # 意象描述（如 "服务器机房，冷色调，绿色数据流"）
    mood: str  # 情绪基调（如 "专业、冷静、可靠"）
    dimensions: str  # 尺寸建议（如 "16:9" 或 "1200x630"）
    keywords: list[str] = field(default_factory=list)  # 关键词辅助生成


@dataclass
class VisualAnchor:
    """视觉锚点（T-016 结构化输出）"""
    section_role: str  # 对应哪个结构部分（如 "opening"）
    concept: str  # 意象描述
    visual_type: Literal["screenshot", "diagram", "photo", "illustration", "none"]
    screenshot_target: str | None = None  # 如果是截图，目标 URL
    diagram_spec: str | None = None  # 如果是图表，规格描述


@dataclass
class SeoMetadata:
    """SEO 元数据（T-016 结构化输出）"""
    title: str  # 文章标题
    description: str  # 搜索结果描述
    keywords: list[str]  # 关键词列表
    excerpt: str  # 文章摘要（前 150 字）


@dataclass
class CompileOutput:
    """Layer 5 编译层完整输出（T-016 结构化输出）

    markdown 是独立完整的产物（纯文本可发布）。
    json 元数据是增强层，供下游工具（Studio、发布系统）使用。
    """
    markdown: str  # 完整的 writer prompt（可喂给 LLM 生成正文）
    hero_brief: HeroBrief | None = None  # 封面图需求
    visual_anchors: list[VisualAnchor] = field(default_factory=list)  # 视觉锚点列表
    seo_metadata: SeoMetadata | None = None  # SEO 元数据
    tags: list[str] = field(default_factory=list)  # 文章标签
    cta: list[str] = field(default_factory=list)  # 下一步行动建议
