"""文风格调系统 — 五维坐标系 + 注入分层 + 中文审美概念映射."""

from __future__ import annotations
from dataclasses import dataclass, field

# ── Injection levels ──

class Injection:
    NONE = "none"
    SUBTLE = "subtle"
    FULL = "full"


# ── StyleVector ──

@dataclass(frozen=True)
class StyleVector:
    density: float   # 疏密 [-1, 1]: -1=稀疏短句, +1=密集长段
    warmth: float    # 冷暖 [-1, 1]: -1=冷客观, +1=暖亲近
    energy: float    # 动静 [-1, 1]: -1=平稳, +1=冲击
    register: float  # 雅俗 [-1, 1]: -1=书面语, +1=口语化
    edge: float      # 锐钝 [-1, 1]: -1=周全, +1=犀利
    injection: str = Injection.FULL
    active: bool = True

    def __post_init__(self):
        for name in ("density", "warmth", "energy", "register", "edge"):
            v = getattr(self, name)
            if not -1.0 <= v <= 1.0:
                raise ValueError(f"{name}={v} out of [-1, 1]")


# ── Dimension → instruction mapping (5 dims × 4 intervals = 20 rules) ──

_RANGES = (-1.0, -0.5, 0.0, 0.5, 1.0)

_DIM_RULES: dict[str, list[str]] = {
    "density": [
        "每段 1-2 句。关键信息单独成段。不堆砌修饰语。",
        "段落偏短，信息点到为止。适当留白。",
        "正常段落长度，信息密度适中。",
        "段落可长，信息密集。允许三句话以上的复合论述。",
    ],
    "warmth": [
        '全程第三人称。不出现"你""我们"。用数据和事实说话，不讲故事。',
        '偶尔用"你"但不拉近距离。保持专业距离感。',
        '用"你"和读者对话。可以讲一个简短的场景（不超过两句）引入问题。',
        '可以用"我们"构建共同体验。用场景和故事说明问题。每 2-3 段有一个读者能代入的瞬间。',
    ],
    "energy": [
        "娓娓道来。用陈述句为主。不用感叹号和反问。节奏平稳，像坐在对面聊天。",
        "偶尔用一个短句制造停顿。大部分段落语气平和。",
        "关键判断用短句。数据句独立成段制造冲击。允许偶尔的反问句。",
        "短句密集。判断句独立成段。可以连续用三句短论点制造节奏感。禁用长修饰语。",
    ],
    "register": [
        "书面语。不用口语词。术语保留英文原文（如 REST API）。句式完整，不省略主语。",
        "正式但不刻板。技术术语中英对照，其余用中文。",
        '可以用"说白了"等口语表达。技术名词仍用规范术语。',
        '像跟同事聊天。可以用类比、比喻、生活场景解释技术概念。允许"这玩意""这东西"等口语。',
    ],
    "edge": [
        "不下判断。多角度呈现。结论留给读者。",
        '给出倾向但保留余地。使用"大多数情况下"，不用"一定""必须"。',
        "有明确判断并给出理由。",
        '判断前置，不拐弯。指出对立观点的具体错误。"X 不是 Y"句式可以使用。',
    ],
}

_DIM_NAMES: dict[str, str] = {
    "density": "疏密",
    "warmth": "冷暖",
    "energy": "动静",
    "register": "雅俗",
    "edge": "锐钝",
}


def _lookup(dim: str, value: float) -> str:
    idx = 0
    for i in range(len(_RANGES) - 1):
        if value >= _RANGES[i]:
            idx = i
    return _DIM_RULES[dim][idx]


# ── Category presets (21 categories) ──

_PRESETS: dict[str, dict] = {
    "tutorial":            {"density":  0.3, "warmth":  0.6, "energy":  0.2, "register": -0.2, "edge":  0.2, "injection": Injection.FULL},
    "opinion":             {"density":  0.1, "warmth":  0.2, "energy":  0.7, "register": -0.1, "edge":  0.9, "injection": Injection.FULL},
    "comparison":          {"density":  0.4, "warmth":  0.0, "energy":  0.2, "register": -0.3, "edge":  0.5, "injection": Injection.FULL},
    "guide":               {"density":  0.3, "warmth":  0.4, "energy":  0.1, "register": -0.3, "edge":  0.4, "injection": Injection.FULL},
    "troubleshooting":     {"density":  0.2, "warmth":  0.1, "energy":  0.3, "register": -0.2, "edge":  0.7, "injection": Injection.FULL},
    "beginner":            {"density":  0.0, "warmth":  0.8, "energy": -0.2, "register":  0.2, "edge": -0.1, "injection": Injection.FULL},
    "case-study":          {"density":  0.0, "warmth":  0.6, "energy":  0.3, "register":  0.1, "edge":  0.5, "injection": Injection.FULL},
    "listicle":            {"density": -0.2, "warmth":  0.5, "energy":  0.3, "register": -0.1, "edge":  0.4, "injection": Injection.FULL},
    "trend":               {"density":  0.3, "warmth":  0.0, "energy":  0.4, "register": -0.4, "edge":  0.6, "injection": Injection.FULL},
    "thought-leadership":  {"density":  0.2, "warmth":  0.1, "energy":  0.6, "register": -0.3, "edge":  1.0, "injection": Injection.FULL},
    "editorial":           {"density":  0.1, "warmth":  0.3, "energy":  0.7, "register": -0.1, "edge":  0.9, "injection": Injection.FULL},
    "resource-roundup":    {"density":  0.2, "warmth":  0.4, "energy":  0.1, "register": -0.2, "edge":  0.3, "injection": Injection.SUBTLE},
    "tool-review":         {"density":  0.1, "warmth": -0.1, "energy":  0.2, "register": -0.3, "edge":  0.5, "injection": Injection.SUBTLE},
    "product-launch":      {"density": -0.2, "warmth":  0.4, "energy":  0.4, "register": -0.1, "edge":  0.6, "injection": Injection.SUBTLE},
    "brand-marketing":     {"density":  0.1, "warmth":  0.5, "energy":  0.5, "register":  0.0, "edge":  0.3, "injection": Injection.SUBTLE},
    "soft-article":        {"density":  0.3, "warmth":  0.2, "energy":  0.2, "register": -0.1, "edge":  0.3, "injection": Injection.SUBTLE},
    "marketing":           {"density": -0.1, "warmth":  0.4, "energy":  0.5, "register":  0.0, "edge":  0.5, "injection": Injection.SUBTLE},
    "announcement":        {"density": -0.5, "warmth": -0.3, "energy":  0.0, "register": -0.5, "edge":  0.4, "injection": Injection.NONE},
    "news":                {"density": -0.4, "warmth": -0.4, "energy":  0.1, "register": -0.5, "edge":  0.3, "injection": Injection.NONE},
    "wp-tech":             {"density":  0.3, "warmth":  0.3, "energy":  0.2, "register": -0.2, "edge":  0.3, "injection": Injection.FULL},
    "book-knowledge":      {"density":  0.0, "warmth":  0.6, "energy": -0.1, "register":  0.1, "edge":  0.2, "injection": Injection.FULL},
}


def get_preset(category: str) -> StyleVector:
    cat = category.lower().strip() if category else ""
    preset = _PRESETS.get(cat)
    if not preset:
        preset = _PRESETS["guide"]
    return StyleVector(**preset)


def get_preset_dict(category: str) -> dict:
    return {
        "density": get_preset(category).density,
        "warmth": get_preset(category).warmth,
        "energy": get_preset(category).energy,
        "register": get_preset(category).register,
        "edge": get_preset(category).edge,
        "injection": get_preset(category).injection,
        "active": get_preset(category).active,
    }


# ── Instruction generation ──

def render_temperament(vector: StyleVector) -> list[str]:
    if not vector.active:
        return []
    dims = [
        ("density", vector.density),
        ("warmth", vector.warmth),
        ("energy", vector.energy),
        ("register", vector.register),
        ("edge", vector.edge),
    ]
    return [_lookup(dim, val) for dim, val in dims]


def render_injection(vector: StyleVector) -> str:
    if not vector.active or vector.injection == Injection.NONE:
        return ""
    instructions = render_temperament(vector)
    if not instructions:
        return ""
    if vector.injection == Injection.SUBTLE:
        return "## 文风要求（轻量校准，遵守即可）\n" + "\n".join(
            f"- {inst}" for inst in [instructions[0], instructions[4]]
        )
    return "## 文风要求（以下指令决定文章的语气和节奏，必须遵守）\n" + "\n".join(
        f"- {inst}" for inst in instructions
    )


# ── Aesthetic concepts ──

_AESTHETIC_CONCEPTS: list[dict[str, str]] = [
    {
        "name": "文气",
        "source": "传统文章学",
        "instruction": "段落间保持呼吸节奏——长段铺陈后接一个判断短句。三段密一段疏。句子长度有意变化，形成内在韵律。",
    },
    {
        "name": "风骨",
        "source": "《文心雕龙》",
        "instruction": '核心判断句前置。不用"或许""可能""似乎"修饰主要论点。论据支撑判断，判断不因论据妥协。',
    },
    {
        "name": "留白",
        "source": "中国传统美学",
        "instruction": "关键结论写出后不停留，不解释。留给读者思考。段落间有意留空，不用过渡句填满。",
    },
    {
        "name": "分寸",
        "source": "传统文章学",
        'instruction': '技术描述精确到数字（"TTFB 从 800ms 降到 200ms"），不写"大幅提升"。情感描述点到为止，不煽情。',
    },
    {
        "name": "意在言外",
        "source": "传统诗学",
        "instruction": "结尾不总结全文。用一个具体画面、一个未解答的问题、或一个假设场景收束。让读者带着思考离开。",
    },
]


def render_aesthetic_concepts(vector: StyleVector | None = None,
                               concepts: list[str] | None = None,
                               category: str | None = None) -> str:
    if vector and vector.injection == Injection.NONE:
        return ""
    if vector and vector.injection == Injection.SUBTLE:
        return ""

    # 品类 → 审美概念映射（T-003）
    _CATEGORY_CONCEPTS: dict[str, list[str]] = {
        "beginner": ["分寸"],
        "tutorial": ["文气", "分寸"],
        "opinion": ["风骨", "文气", "意在言外"],
        "editorial": ["风骨", "文气", "意在言外"],
        "comparison": ["分寸", "文气"],
        "troubleshooting": ["分寸", "风骨"],
        "case-study": ["文气", "意在言外"],
    }

    selected = _AESTHETIC_CONCEPTS

    # 优先级：显式指定 > 品类映射 > 全部
    if concepts:
        selected = [c for c in selected if c["name"] in concepts]
    elif category:
        cat_key = category.lower().strip()
        mapped = _CATEGORY_CONCEPTS.get(cat_key)
        if mapped:
            selected = [c for c in selected if c["name"] in mapped]

    lines = ["## 写作审美（来自中文写作经典，内化为你的本能）"]
    for c in selected:
        lines.append(f"- {c['instruction']}")
    return "\n".join(lines)


# ── Full style block for writer prompt ──

def render_style_block(category: str, overrides: dict | None = None) -> str:
    preset = get_preset(category)
    if not preset.active and not overrides:
        return ""
    if overrides:
        fields = {
            "density": overrides.get("density", preset.density),
            "warmth": overrides.get("warmth", preset.warmth),
            "energy": overrides.get("energy", preset.energy),
            "register": overrides.get("register", preset.register),
            "edge": overrides.get("edge", preset.edge),
            "injection": overrides.get("injection", preset.injection),
            "active": overrides.get("active", preset.active),
        }
        vector = StyleVector(**fields)
    else:
        vector = preset

    if not vector.active:
        return ""
    parts = []
    injection_block = render_injection(vector)
    if injection_block:
        parts.append(injection_block)
    aesthetic_block = render_aesthetic_concepts(vector, category=category)
    if aesthetic_block:
        parts.append(aesthetic_block)
    return "\n\n".join(parts) if parts else ""


# ── Humanizer dimension alignment (design doc: Phase 3) ──

STYLE_TO_HUMANIZER: dict[str, str] = {
    "density": "节奏",
    "warmth": "信任度",
    "energy": "直接性",
    "register": "精炼度",
    "edge": "真实性",
}
