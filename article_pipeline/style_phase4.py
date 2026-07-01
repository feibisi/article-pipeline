"""文风格调系统 Phase 4 — 用 5 维坐标替换 genre rules if-else

核心思想：
1. 不再硬编码品类规则，而是根据 style 坐标动态生成
2. 每个品类有一个 style preset（已有），从 preset 推导规则
3. 规则分为：句式规则、节奏规则、姿态规则
"""

from article_pipeline.style import StyleVector, render_temperament
from typing import Literal


# 规则类型
RuleType = Literal["sentence", "rhythm", "stance", "structure", "data"]


def _render_sentence_rules(vector: StyleVector) -> list[str]:
    """从 density + register 推导句式规则"""
    rules = []

    # density → 句子长度
    if vector.density < -0.3:
        rules.append("每段 1-2 句。关键信息单独成段。不堆砌修饰语。")
    elif vector.density > 0.3:
        rules.append("段落可长，信息密集。允许三句话以上的复合论述。")

    # register → 语言风格
    if vector.register < -0.5:
        rules.append("书面语。不用口语词。句式完整，不省略主语。")
    elif vector.register > 0.5:
        rules.append("像跟同事聊天。可以用类比、比喻、生活场景解释技术概念。")

    # density → 标点使用
    if vector.density < -0.2:
        rules.append("全篇——不超过3个。能用句号的地方用句号。")

    # energy → 判断句
    if vector.energy > 0.5:
        rules.append("判断句独立成段。可以连续用三句短论点制造节奏感。")

    return rules


def _render_rhythm_rules(vector: StyleVector) -> list[str]:
    """从 energy + density 推导节奏规则"""
    rules = []

    # energy → 节奏类型
    if vector.energy < -0.5:
        rules.append("娓娓道来。用陈述句为主。不用感叹号和反问。节奏平稳。")
    elif vector.energy > 0.5:
        rules.append("短句密集推进。判断句独立成段。禁用长修饰语。")

    # density → 段落呼吸
    if vector.density < -0.3:
        rules.append("段落间保持呼吸节奏——长段铺陈后接一个判断短句。三段密一段疏。")

    # warmth → 过渡
    if vector.warmth < -0.3:
        rules.append("段落之间不用'此外''另外''与此同时'衔接，让内容自然过渡。")
    elif vector.warmth > 0.3:
        rules.append("用场景和故事说明问题。每 2-3 段有一个读者能代入的瞬间。")

    return rules


def _render_stance_rules(vector: StyleVector) -> list[str]:
    """从 warmth + edge 推导姿态规则"""
    rules = []

    # warmth → 叙述姿态
    if vector.warmth < -0.5:
        rules.append("全程第三人称。不出现'你''我们'。用数据和事实说话，不讲故事。")
    elif vector.warmth > 0.5:
        rules.append("像跟你最聪明但没耐心的朋友解释一件事。他知道你什么意思所以不铺垫。")

    # edge → 判断态度
    if vector.edge < -0.3:
        rules.append("不下判断。多角度呈现。结论留给读者。")
    elif vector.edge > 0.5:
        rules.append("判断前置，不拐弯。核心判断句前置。不用'或许''可能''似乎'修饰主要论点。")

    # warmth + edge → 情感控制
    if vector.warmth < 0 and vector.edge < 0:
        rules.append("情感描述点到为止，不煽情。")

    return rules


def _render_structure_rules(vector: StyleVector, category: str = "") -> list[str]:
    """从品类 + density 推导结构规则"""
    rules = []

    # 品类特定规则（从 genre_rules 提炼）
    if category == "tutorial":
        rules.append("先给例子，再解释原理。读者是来解决问题的，不是来上课的。")
        rules.append("代码块后面必须跟一句人话解释这段代码做了什么。")
        rules.append("每一步操作都要说明'如果不这样做会怎样'——教避坑比教操作更有用。")
    elif category == "opinion":
        rules.append("每节用一个具体场景或问题开头，不用概念定义开头。")
    elif category == "case-study":
        rules.append("教程和案例研究类文章可以用假设场景说明问题。")

    # density → 结构细节
    if vector.density < -0.2:
        rules.append("一句话一个意思。不用从句嵌套。每段不超过3句话，超过就拆。")

    return rules


def _render_data_rules(vector: StyleVector) -> list[str]:
    """从 edge + warmth 推导数据使用规则"""
    rules = []

    # edge → 数据呈现
    if vector.edge > 0.3:
        rules.append("数据后面必须跟一句解释，说明这个数字意味着什么。")

    # warmth → 数据选择
    if vector.warmth < -0.3:
        rules.append("素材中未确认的数据、数字、时间、URL、地址——直接跳过不写。")

    # edge → 精确度
    if vector.edge > 0.5:
        rules.append("技术描述精确到数字（'TTFB 从 800ms 降到 200ms'），不写'大幅提升'。")

    return rules


def render_genre_rules(category: str, override_vector: dict | None = None) -> dict:
    """Phase 4: 用 style 坐标生成品类规则，替换硬编码 if-else

    Args:
        category: 品类（tutorial, opinion, case-study 等）
        override_vector: 覆盖默认 preset 的坐标值

    Returns:
        {
            "sentence": [...],  # 句式规则
            "rhythm": [...],    # 节奏规则
            "stance": [...],    # 姿态规则
            "structure": [...], # 结构规则
            "data": [...],      # 数据规则
        }
    """
    from article_pipeline.style import get_preset

    # 获取品类 preset
    preset = get_preset(category)
    if override_vector:
        # 合并覆盖
        import copy
        vector = StyleVector(**{**preset.__dict__, **override_vector})
    else:
        vector = preset

    # 关闭 active 不生成规则
    if not vector.active:
        return {}

    rules = {
        "sentence": _render_sentence_rules(vector),
        "rhythm": _render_rhythm_rules(vector),
        "stance": _render_stance_rules(vector),
        "structure": _render_structure_rules(vector, category),
        "data": _render_data_rules(vector),
    }

    return rules


def format_rules_as_prompt(rules: dict) -> str:
    """将规则格式化为 LLM prompt"""
    if not rules:
        return ""

    sections = []

    # 句式规则
    if rules.get("sentence"):
        sections.append("### 句式要求")
        for r in rules["sentence"]:
            sections.append(f"- {r}")

    # 节奏规则
    if rules.get("rhythm"):
        sections.append("### 节奏要求")
        for r in rules["rhythm"]:
            sections.append(f"- {r}")

    # 姿态规则
    if rules.get("stance"):
        sections.append("### 写作姿态")
        for r in rules["stance"]:
            sections.append(f"- {r}")

    # 结构规则
    if rules.get("structure"):
        sections.append("### 结构要求")
        for r in rules["structure"]:
            sections.append(f"- {r}")

    # 数据规则
    if rules.get("data"):
        sections.append("### 数据使用")
        for r in rules["data"]:
            sections.append(f"- {r}")

    return "\n".join(sections)


if __name__ == "__main__":
    # 测试 Phase 4 规则生成
    print("=== Phase 4: Tutorial 品类规则 ===")
    rules = render_genre_rules("tutorial")
    print(format_rules_as_prompt(rules))

    print("\n=== Phase 4: Opinion 品类规则 ===")
    rules = render_genre_rules("opinion")
    print(format_rules_as_prompt(rules))
