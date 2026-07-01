# Article Pipeline 级联编译类型化契约

from dataclasses import dataclass, field
from typing import Literal

__all__ = ["SynthesisOutput", "FrameworkOutput", "StyleOutput", "ProsodyOutput"]


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
