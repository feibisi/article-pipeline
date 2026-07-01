"""语感引导层 — Prosody 范本加载与节奏指导."""

from __future__ import annotations
from pathlib import Path
from typing import Literal

from article_pipeline.contracts import ProsodyOutput, StyleOutput
from article_pipeline.style import get_preset

# 范本类型定义

SampleType = Literal["short_push", "flowing", "staccato", "scaffold"]

# 能量 → 范本映射
# high energy → short_push（短句推进型）
# low energy → flowing（从容铺陈型）
# 也可根据 density 进一步细化
_ENERGY_TO_SAMPLE: dict[str, SampleType] = {
    "high": "short_push",
    "low": "flowing",
    "mid": "flowing",  # 默认倾向 flowing
}

# 品类 → 范本默认映射（覆盖 energy 规则）
_CATEGORY_DEFAULT_SAMPLE: dict[str, SampleType] = {
    "opinion": "short_push",
    "editorial": "short_push",
    "thought-leadership": "staccato",
    "troubleshooting": "scaffold",
    "tutorial": "scaffold",
    "guide": "flowing",
    "beginner": "flowing",
    "case-study": "flowing",
    "announcement": "staccato",
    "news": "short_push",
}

# 硬性禁止列表，品类无关通用规则

_COMMON_NEGATIVE_CONSTRAINTS = [
    "不使用「不得不说」「可以说」等无意义的填充词",
    "不使用「众所周知」「不言而喻」等预设读者同意的表达",
    "不使用三个以上的连续感叹号",
    "不使用「众所周知」——如果真众所周知就不必写",
    "不使用「...」（省略号）结尾制造悬念",
    "不使用「首先...其次...最后」的机械过渡",
    "不使用「值得注意的是」「需要指出的是」等虚指引入",
    "不使用「值得一提的是」——要么重要要么不写",
    "不使用「非常」「极其」「特别」等空洞程度副词",
    "不使用「换句话说」「也就是说」的重复表达",
    "不使用「显而易见」——对作者显而易见不对读者显而易见",
]

# 节奏提示模板

_RHYTHM_HINTS: dict[SampleType, str] = {
    "short_push": "短句密集推进，判断句独立成段，关键数据单独一行",
    "flowing": "从容铺陈，允许长段展开，用完整句子承载信息",
    "staccato": "断奏节奏——短语有力，段落间有呼吸感",
    "scaffold": "层层递进——从简单到复杂，从已知到未知，每段建立在前一段之上",
}


# 路径工具

def _get_genre_base_path() -> Path:
    """获取 genres 目录路径."""
    return Path(__file__).parent / "genres"


def _get_prosody_dir(genre: str) -> Path:
    """获取指定品类的 prosody_samples 目录."""
    base = _get_genre_base_path()
    genre_dir = base / genre.lower().strip()
    if not genre_dir.exists():
        raise ValueError(f"Genre directory not found: {genre_dir}")
    prosody_dir = genre_dir / "prosody_samples"
    if not prosody_dir.exists():
        raise ValueError(f"Prosody samples directory not found: {prosody_dir}")
    return prosody_dir


# 公共 API

def load_prosody_samples(genre: str, sample_type: SampleType | None = None) -> list[str]:
    """加载指定品类的语感范本.

    Args:
        genre: 品类名称（如 tutorial, opinion）
        sample_type: 范本类型，如 None 则加载所有 .txt 文件

    Returns:
        范本文本列表，去除空行和 placeholder 文件

    Raises:
        ValueError: 品类目录不存在
    """
    prosody_dir = _get_prosody_dir(genre)

    if sample_type:
        target_files = [prosody_dir / f"{sample_type}.txt"]
    else:
        target_files = sorted(prosody_dir.glob("*.txt"))

    samples = []
    for filepath in target_files:
        if filepath.name.startswith("."):
            continue
        content = filepath.read_text(encoding="utf-8").strip()
        if content:
            samples.append(content)

    return samples


def _select_sample_type(style: StyleOutput, genre: str) -> SampleType:
    """根据风格坐标选择范本类型.

    优先级：
    1. 品类默认映射（_CATEGORY_DEFAULT_SAMPLE）
    2. energy 坐标（>0.5 → short_push, <-0.5 → flowing）
    3. 默认 flowing
    """
    # 1. 品类默认
    cat_key = genre.lower().strip()
    if cat_key in _CATEGORY_DEFAULT_SAMPLE:
        return _CATEGORY_DEFAULT_SAMPLE[cat_key]

    # 2. energy 坐标
    energy = style.vector.get("energy", 0)
    if energy > 0.5:
        return "short_push"
    if energy < -0.5:
        return "flowing"

    # 3. 默认
    return "flowing"


def _build_negative_constraints(genre: str) -> str:
    """构建硬性禁止列表.

    通用规则 + 品类特定规则（如果有的话）。
    """
    # 品类特定禁止（可扩展）
    _CATEGORY_SPECIFIC: dict[str, list[str]] = {
        "tutorial": [
            "不使用「你只需要」「你只需」——直接告诉怎么做",
            "不使用「很简单」「很容易」——对读者可能不简单",
        ],
        "opinion": [
            "不使用「我个人认为」「笔者觉得」——观点本身就是你的",
            "不使用「也许」「可能」——要么判断要么保留",
        ],
        "news": [
            "不使用任何感叹号",
            "不使用形容词评价，只用陈述事实",
        ],
    }

    cat_key = genre.lower().strip()
    constraints = _COMMON_NEGATIVE_CONSTRAINTS.copy()
    if cat_key in _CATEGORY_SPECIFIC:
        constraints.extend(_CATEGORY_SPECIFIC[cat_key])

    return "\n".join(f"- {c}" for c in constraints)


def build_prosody_output(style: StyleOutput, genre: str) -> ProsodyOutput:
    """根据风格坐标构建语感输出.

    Args:
        style: 风格输出（包含 vector 和 constraints）
        genre: 品类名称

    Returns:
        ProsodyOutput 包含范本、类型、禁止列表、节奏提示
    """
    sample_type = _select_sample_type(style, genre)

    # 加载范本（优先品类特定范本，如无则使用通用范本）
    samples = load_prosody_samples(genre, sample_type)
    if not samples:
        # 品类特定范本不存在，尝试加载所有范本
        samples = load_prosody_samples(genre)

    # 限制范本数量为 2-3 个
    samples = samples[:3]

    negative_constraints = _build_negative_constraints(genre)
    rhythm_hint = _RHYTHM_HINTS.get(sample_type, "标准节奏——句子长度有变化，段落间有呼吸")

    return ProsodyOutput(
        samples=samples,
        sample_type=sample_type,
        negative_constraints=negative_constraints,
        rhythm_hint=rhythm_hint,
        freeform_note="",
    )


def run_prosody(style: StyleOutput, genre: str) -> ProsodyOutput:
    """Prosody 层主函数.

    Args:
        style: 风格输出（StyleOutput）
        genre: 品类名称（如 tutorial, opinion）

    Returns:
        ProsodyOutput 包含：
        - samples: 2-3 个范本段落
        - sample_type: 范本类型
        - negative_constraints: 硬性禁止列表
        - rhythm_hint: 一句话节奏提示

    Example:
        >>> from article_pipeline.style import run_style
        >>> style_out = run_style("tutorial")
        >>> prosody_out = run_prosody(style_out, "tutorial")
        >>> print(prosody_out.sample_type)  # "scaffold"
        >>> print(prosody_out.rhythm_hint)  # "层层递进——从简单到复杂..."
    """
    return build_prosody_output(style, genre)


# 独立运行入口，用于测试

if __name__ == "__main__":
    # 快速测试：加载 tutorial 品类的 Prosody
    from article_pipeline.style import run_style

    test_genre = "tutorial"
    style_out = run_style(test_genre)
    prosody_out = run_prosody(style_out, test_genre)

    print(f"Genre: {test_genre}")
    print(f"Sample Type: {prosody_out.sample_type}")
    print(f"Rhythm Hint: {prosody_out.rhythm_hint}")
    print(f"Samples Loaded: {len(prosody_out.samples)}")
    if prosody_out.samples:
        print(f"First Sample Preview: {prosody_out.samples[0][:100]}...")
