"""级联编译集成测试 - 验证各层接口和数据流。

不调用真实 LLM API，使用 mock 数据验证：
1. synthesis → framework → style → prosody → compile → outline 数据流
2. 各层输出格式兼容下一层输入
3. 类型契约正确传递
"""

import json

import pytest
from article_pipeline.contracts import (
    SynthesisOutput,
    FrameworkOutput,
    StyleOutput,
    ProsodyOutput,
)
from article_pipeline.framework import build_framework_output
from article_pipeline.style import get_preset_dict
from article_pipeline.prosody import run_prosody
from article_pipeline.compile import run_compile, compile_to_json
from article_pipeline.outline import generate_outline_from_layers


class TestCascadeDataFlow:
    """测试级联编译数据流"""

    def test_synthesis_to_framework(self):
        """SynthesisOutput 可被 framework 层正确处理"""
        synthesis = SynthesisOutput(
            core_judgment="Nginx 缓存可显著降低后端压力",
            evidence_for=[{"source": "Nginx 官方", "claim": "缓存命中率 95%"}],
            evidence_against=[],
            conflicts=[],
            unique_claims=["实测显示缓存减少 70% 请求"],
            differentiation="包含 elementary 实测的性能数据",
            confidence=0.8,
        )

        # 加载 framework.yaml
        from article_pipeline.framework import load_framework_yaml
        framework_data = load_framework_yaml("tutorial")
        framework = build_framework_output(framework_data, synthesis, "tutorial")

        assert framework.method == "cognitive_scaffold"
        assert framework.takeaway
        assert len(framework.structure) > 0
        assert "opening" in [s.get("role") for s in framework.structure]

    def test_framework_to_style(self):
        """Framework 可配合 style 预设使用"""
        framework = FrameworkOutput(
            method="cognitive_scaffold",
            structure=[{"role": "opening", "purpose": "展示终态"}],
            takeaway="Nginx 缓存有效",
            reader_entry_state="读者认为缓存复杂",
            reader_exit_state="读者理解了基本配置",
        )

        style_dict = get_preset_dict("tutorial")
        assert "density" in style_dict
        assert "warmth" in style_dict
        assert -1.0 <= style_dict["density"] <= 1.0

    def test_style_to_prosody(self):
        """StyleOutput 可被 prosody 层使用"""
        style = StyleOutput(
            vector={"density": 0.3, "warmth": 0.6, "energy": 0.2, "register": -0.2, "edge": 0.2},
            constraints={"require": ["展示终态"], "avoid": ["抽象理论先行"]},
            rendered_instructions="略",
            aesthetic_concepts=["分寸"],
        )

        prosody = run_prosody(style, "tutorial")

        assert prosody.sample_type in ["short_push", "flowing", "staccato", "scaffold"]
        assert prosody.rhythm_hint
        assert prosody.negative_constraints

    def test_all_layers_to_compile(self):
        """全部层输出可被 compile 层组装"""
        framework = FrameworkOutput(
            method="cognitive_scaffold",
            structure=[
                {"role": "opening", "purpose": "展示终态", "h2_title": "终态预览"},
                {"role": "body", "purpose": "逐步执行", "h2_title": "配置步骤"},
            ],
            takeaway="Nginx 缓存可显著降低后端压力",
            reader_entry_state="读者认为缓存很复杂",
            reader_exit_state="读者理解了 Nginx 缓存的基本配置",
            visual_anchors=[
                {
                    "section_role": "opening",
                    "concept": "Nginx 配置界面",
                    "visual_type": "screenshot",
                    "screenshot_target": "https://nginx.org/en/docs/",
                }
            ],
        )

        style = StyleOutput(
            vector={"density": 0.3, "warmth": 0.6, "energy": 0.2, "register": -0.2, "edge": 0.2},
            constraints={"require": ["展示终态", "每步有验证"]},
            rendered_instructions="略",
            aesthetic_concepts=["分寸"],
        )

        prosody = ProsodyOutput(
            samples=["示例范本..."],
            sample_type="scaffold",
            negative_constraints="不要说'综上所述'",
            rhythm_hint="层层递进",
        )

        material = {
            "evidence_for": [{"claim": "实测显示缓存减少 70% 请求", "source": "Nginx 官方"}],
        }

        compile_output = run_compile(
            framework=framework,
            style=style,
            prosody=prosody,
            material=material,
            keyword="Nginx 缓存",
            category="tutorial",
        )

        assert compile_output.markdown
        assert "## 核心判断" in compile_output.markdown
        assert compile_output.hero_brief
        assert len(compile_output.visual_anchors) > 0
        assert compile_output.seo_metadata
        assert compile_output.tags

    def test_compile_to_json(self):
        """CompileOutput 可序列化为 JSON"""
        from article_pipeline.contracts import CompileOutput, HeroBrief, SeoMetadata

        compile_output = CompileOutput(
            markdown="测试内容",
            hero_brief=HeroBrief(
                concept="测试概念",
                mood="专业",
                dimensions="16:9",
                keywords=["nginx"],
            ),
            visual_anchors=[],
            seo_metadata=SeoMetadata(
                title="测试标题",
                description="测试描述",
                keywords=["nginx"],
                excerpt="摘要",
            ),
            tags=["nginx", "cache"],
            cta=["收藏本文"],
        )

        json_str = compile_to_json(compile_output)
        assert json_str
        assert "测试概念" in json_str
        assert "测试标题" in json_str

    def test_outline_from_layers_format(self, monkeypatch):
        """generate_outline_from_layers 真的把上游各层的数据带进了 prompt。"""
        synthesis_data = {
            "core_judgment": "Nginx 缓存可显著降低后端压力",
            "evidence_for": [{"source": "官方", "claim": "缓存有效"}],
            "evidence_against": [],
            "conflicts": [],
            "unique_claims": ["实测减少 70% 请求"],
            "differentiation": "包含 elementary 实测的性能数据",
            "confidence": 0.8,
        }

        framework_data = {
            "method": "cognitive_scaffold",
            "structure": [
                {"role": "opening", "purpose": "展示终态", "h2_title": "终态预览"},
                {"role": "body", "purpose": "逐步执行", "h2_title": "配置步骤"},
            ],
            "takeaway": "Nginx 缓存有效",
            "reader_entry_state": "读者认为缓存复杂",
            "reader_exit_state": "读者理解了基本配置",
        }

        style_data = {
            "vector": {
                "density": 0.3,
                "warmth": 0.6,
                "energy": 0.2,
                "register": -0.2,
                "edge": 0.2,
                "injection": "full",
                "active": True,
            },
            "constraints": {"require": ["展示终态"], "avoid": []},
            "rendered_instructions": "略",
            "aesthetic_concepts": [],
        }

        prosody_data = {
            "samples": ["示例范本..."],
            "sample_type": "scaffold",
            "negative_constraints": "不要说'综上所述'",
            "rhythm_hint": "层层递进",
        }

        # Previously this test asserted only the truthiness of the four dict
        # literals defined above — generate_outline_from_layers was imported at
        # the top of the file and never called, so the function it claimed to
        # cover had zero coverage. Call it for real, with the LLM stubbed so the
        # test stays offline, and assert the cascade actually reaches the prompt.
        import article_pipeline.outline as O

        seen = {}

        def fake_api(prompt):
            seen["prompt"] = prompt
            # _try_api returns the outline dict FLAT (outline.py:450-452).
            return {
                "title": "Nginx 缓存配置",
                "differentiation": "包含 elementary 实测的命中率数据，搜索结果均未提供",
                "sections": [{"h2": "终态预览"}, {"h2": "配置步骤"}],
            }

        monkeypatch.setattr(O, "_try_api", fake_api)

        outline = O.generate_outline_from_layers(
            keyword="Nginx 缓存",
            category="tutorial",
            platform="wptea",
            synthesis_output=synthesis_data,
            framework_output=framework_data,
            style_output=style_data,
            prosody_output=prosody_data,
        )
        assert isinstance(outline, dict), f"unexpected return type: {type(outline)}"
        assert "error" not in outline, outline

        # Every upstream layer must be represented in the prompt. A regression
        # that silently drops one of these is exactly the kind of cascade bug
        # asserting on dict literals could never catch.
        prompt = seen["prompt"]
        assert "Nginx 缓存可显著降低后端压力" in prompt, "synthesis core_judgment dropped"
        assert "实测减少 70% 请求" in prompt, "synthesis unique_claims dropped"
        assert "终态预览" in prompt and "配置步骤" in prompt, "framework structure dropped"
        assert "展示终态" in prompt, "style constraints dropped"
        assert "层层递进" in prompt, "prosody rhythm_hint dropped"

        # And the differentiation gate must reject an outline that has no
        # differentiation — this is the only place upstream of writing where
        # "this article has no reason to exist" can still be caught cheaply.
        monkeypatch.setattr(O, "_try_api", lambda p: {"title": "x", "sections": []})
        monkeypatch.setattr(O, "_try_ollama",
                            lambda p, u, m: {"error": "unavailable"})
        rejected = O.generate_outline_from_layers(
            keyword="Nginx 缓存", category="tutorial", platform="wptea",
            synthesis_output=synthesis_data, framework_output=framework_data,
        )
        assert rejected.get("error") == "differentiation_rejected"


class TestGenreCoverage:
    """测试品类覆盖"""

    def test_all_21_genres_have_style_preset(self):
        """所有 21 个品类都有风格预设"""
        genres = [
            "tutorial", "opinion", "comparison", "guide", "troubleshooting",
            "beginner", "case-study", "listicle", "trend", "thought-leadership",
            "editorial", "tool-review", "resource-roundup", "product-launch",
            "brand-marketing", "soft-article", "marketing", "announcement",
            "news", "wp-tech", "book-knowledge",
        ]

        for genre in genres:
            preset = get_preset_dict(genre)
            assert preset is not None
            assert "density" in preset
            assert "warmth" in preset

    def test_all_genres_have_prosody(self):
        """所有品类都有 prosody 目录"""
        from pathlib import Path

        import article_pipeline

        # Resolve relative to the installed package, not the cwd. The previous
        # `Path("article_pipeline/genres")` failed spuriously whenever pytest was
        # invoked from anywhere but the repo root.
        genres_dir = Path(article_pipeline.__file__).parent / "genres"
        # 品类名 → 目录名映射（带连字符的品类名）
        genre_to_dir = {
            "tutorial": "tutorial",
            "opinion": "opinion",
            "comparison": "comparison",
            "guide": "guide",
            "troubleshooting": "troubleshooting",
            "beginner": "beginner",
            "case-study": "case-study",
            "listicle": "listicle",
            "trend": "trend",
            "thought-leadership": "thought-leadership",
            "editorial": "editorial",
            "tool-review": "tool-review",
            "resource-roundup": "resource-roundup",
            "product-launch": "product-launch",
            "brand-marketing": "brand-marketing",
            "soft-article": "soft-article",
            "marketing": "marketing",
            "announcement": "announcement",
            "news": "news",
            "wp-tech": "wp-tech",
            "book-knowledge": "book-knowledge",
        }

        for genre, dir_name in genre_to_dir.items():
            prosody_dir = genres_dir / dir_name / "prosody_samples"
            assert prosody_dir.exists(), f"{genre} 缺少 prosody_samples 目录"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
