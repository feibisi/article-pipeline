"""Tests for style module — 5-dimension coordinate system."""
import pytest
from article_pipeline.style import (
    StyleVector, Injection,
    get_preset, get_preset_dict,
    render_temperament, render_injection,
    render_aesthetic_concepts, render_style_block,
    STYLE_TO_HUMANIZER, _DIM_RULES,
)

ALL_CATEGORIES = [
    "tutorial", "opinion", "comparison", "guide", "troubleshooting",
    "beginner", "case-study", "listicle", "trend", "thought-leadership",
    "editorial", "resource-roundup", "tool-review", "product-launch",
    "brand-marketing", "soft-article", "marketing", "announcement",
    "news", "wp-tech", "book-knowledge",
]


# ── StyleVector ──

class TestStyleVector:
    def test_valid_creation(self):
        v = StyleVector(0.0, 0.0, 0.0, 0.0, 0.0)
        assert v.density == 0.0

    def test_boundary_values(self):
        v = StyleVector(-1.0, -1.0, -1.0, -1.0, -1.0)
        assert v.density == -1.0
        v2 = StyleVector(1.0, 1.0, 1.0, 1.0, 1.0)
        assert v2.edge == 1.0

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            StyleVector(1.5, 0, 0, 0, 0)
        with pytest.raises(ValueError):
            StyleVector(0, 0, 0, 0, -2.0)

    def test_frozen(self):
        v = StyleVector(0.1, 0.2, 0.3, 0.4, 0.5)
        with pytest.raises(AttributeError):
            v.density = 0.9

    def test_default_injection(self):
        v = StyleVector(0, 0, 0, 0, 0)
        assert v.injection == Injection.FULL
        assert v.active is True


# ── get_preset ──

class TestGetPreset:
    def test_all_categories_have_presets(self):
        for cat in ALL_CATEGORIES:
            v = get_preset(cat)
            assert isinstance(v, StyleVector)
            assert v.active

    def test_known_values(self):
        v = get_preset("tutorial")
        assert v.density == pytest.approx(0.3)
        assert v.warmth == pytest.approx(0.6)
        assert v.injection == Injection.FULL

        v = get_preset("announcement")
        assert v.density == pytest.approx(-0.5)
        assert v.injection == Injection.NONE

    def test_unknown_falls_back_to_guide(self):
        v = get_preset("nonexistent-category")
        guide = get_preset("guide")
        assert v.density == guide.density

    def test_empty_string_falls_back(self):
        v = get_preset("")
        guide = get_preset("guide")
        assert v.density == guide.density

    def test_case_insensitive(self):
        assert get_preset("Tutorial").density == get_preset("tutorial").density

    def test_none_falls_back(self):
        v = get_preset(None)
        guide = get_preset("guide")
        assert v.density == guide.density


# ── get_preset_dict ──

class TestGetPresetDict:
    def test_returns_dict_with_all_keys(self):
        d = get_preset_dict("wp-tech")
        assert set(d.keys()) == {"density", "warmth", "energy", "register", "edge",
                                  "injection", "active"}


# ── render_temperament ──

class TestRenderTemperament:
    def test_returns_5_instructions(self):
        v = get_preset("tutorial")
        insts = render_temperament(v)
        assert len(insts) == 5
        assert all(isinstance(s, str) and len(s) > 5 for s in insts)

    def test_inactive_returns_empty(self):
        v = StyleVector(0, 0, 0, 0, 0, active=False)
        assert render_temperament(v) == []

    def test_boundary_minus_one(self):
        v = StyleVector(-1.0, -1.0, -1.0, -1.0, -1.0)
        insts = render_temperament(v)
        assert "每段 1-2 句" in insts[0]
        assert "第三人称" in insts[1]

    def test_boundary_plus_one(self):
        v = StyleVector(1.0, 1.0, 1.0, 1.0, 1.0)
        insts = render_temperament(v)
        assert "信息密集" in insts[0]
        assert "共同体验" in insts[1]
        assert "短句密集" in insts[2]
        assert "同事聊天" in insts[3]
        assert "判断前置" in insts[4]


# ── render_injection ──

class TestRenderInjection:
    def test_none_level_empty(self):
        v = get_preset("announcement")
        assert render_injection(v) == ""

    def test_subtle_2_instructions(self):
        v = get_preset("marketing")
        block = render_injection(v)
        assert block.count("\n- ") == 2
        assert "轻量校准" in block

    def test_full_5_instructions(self):
        v = get_preset("tutorial")
        block = render_injection(v)
        assert block.count("\n- ") == 5
        assert "文风要求" in block

    def test_inactive_empty(self):
        v = StyleVector(0, 0, 0, 0, 0, active=False)
        assert render_injection(v) == ""


# ── render_aesthetic_concepts ──

class TestRenderAestheticConcepts:
    def test_full_includes_all_5(self):
        block = render_aesthetic_concepts()
        assert "文气" not in block  # names not in output
        assert "呼吸节奏" in block
        assert "核心判断" in block
        assert "留白" not in block  # name
        assert "不留" in block or "停" in block  # instruction text

    def test_none_injection_empty(self):
        v = get_preset("announcement")
        assert render_aesthetic_concepts(v) == ""

    def test_subtle_injection_empty(self):
        v = get_preset("marketing")
        assert render_aesthetic_concepts(v) == ""

    def test_filter_by_name(self):
        block = render_aesthetic_concepts(concepts=["风骨"])
        assert "核心判断" in block
        assert "呼吸节奏" not in block


# ── render_style_block ──

class TestRenderStyleBlock:
    def test_none_category_empty(self):
        assert render_style_block("announcement") == ""

    def test_full_category_has_both_sections(self):
        block = render_style_block("tutorial")
        assert "文风要求" in block
        assert "写作审美" in block

    def test_subtle_category_no_aesthetic(self):
        block = render_style_block("marketing")
        assert "文风要求" in block
        assert "写作审美" not in block

    def test_overrides_applied(self):
        block = render_style_block("tutorial", {"edge": 0.8})
        assert "判断前置" in block

    def test_override_to_none(self):
        block = render_style_block("tutorial", {"injection": Injection.NONE})
        assert block == ""

    def test_override_inactive(self):
        block = render_style_block("tutorial", {"active": False})
        assert block == ""


# ── Humanizer alignment ──

class TestHumanizerAlignment:
    def test_5_dimensions_mapped(self):
        assert len(STYLE_TO_HUMANIZER) == 5
        assert set(STYLE_TO_HUMANIZER.keys()) == {"density", "warmth", "energy", "register", "edge"}
        assert set(STYLE_TO_HUMANIZER.values()) == {"节奏", "信任度", "直接性", "精炼度", "真实性"}


# ── Dimension coverage ──

class TestDimensionCoverage:
    def test_all_dims_have_4_rules(self):
        for dim, rules in _DIM_RULES.items():
            assert len(rules) == 4, f"{dim} has {len(rules)} rules, expected 4"
