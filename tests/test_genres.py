"""测试 genres yaml 加载与 style.py 硬编码等价"""

import pytest
import yaml
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "article_pipeline"))
from style import _PRESETS, Injection

GENRES_DIR = Path(__file__).parent.parent / "article_pipeline" / "genres"


def test_all_genres_have_manifest():
    """每个品类目录都有 manifest.yaml"""
    for category in _PRESETS.keys():
        manifest_path = GENRES_DIR / category / "manifest.yaml"
        assert manifest_path.exists(), f"{category} 缺少 manifest.yaml"


def test_manifest_injection_level_matches():
    """manifest.yaml 的 injection_level 与 _PRESETS 一致"""
    for category, preset in _PRESETS.items():
        manifest_path = GENRES_DIR / category / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        expected = preset["injection"].lower()  # FULL -> full
        actual = manifest.get("injection_level")
        assert actual == expected, f"{category}: injection_level 期望 {expected}, 实际 {actual}"


def test_style_preset_vector_matches():
    """style_preset.yaml 的 vector 与 _PRESETS 一致"""
    for category, preset in _PRESETS.items():
        preset_path = GENRES_DIR / category / "style_preset.yaml"
        with open(preset_path) as f:
            style_data = yaml.safe_load(f)

        vector = style_data.get("vector", {})
        for dim in ["density", "warmth", "energy", "register", "edge"]:
            expected = preset[dim]
            actual = vector.get(dim)
            assert actual == expected, f"{category}.{dim}: 期望 {expected}, 实际 {actual}"


def test_all_21_categories_exist():
    """21 个品类目录都存在"""
    expected_categories = {
        "tutorial", "opinion", "comparison", "guide", "troubleshooting",
        "beginner", "case-study", "listicle", "trend", "thought-leadership",
        "editorial", "resource-roundup", "tool-review", "product-launch",
        "brand-marketing", "soft-article", "marketing", "announcement",
        "news", "wp-tech", "book-knowledge"
    }
    actual_categories = {
        d.name for d in GENRES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    }
    assert actual_categories == expected_categories, f"品类不匹配: 缺少 {expected_categories - actual_categories}, 多余 {actual_categories - expected_categories}"
