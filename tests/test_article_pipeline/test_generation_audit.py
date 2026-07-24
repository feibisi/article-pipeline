"""Generation-layer audit regression tests.

Covers the cascade wiring defects found in the generation layer:
- PROSODY was computed and discarded; writer hardcoded a duplicate ban list.
- FRAMEWORK discarded framework.yaml's h2_title / pattern / principles /
  anti_patterns, and its preferred/fallback framework resolution was dead code.
- Genre labels with underscores crashed PROSODY and silently downgraded
  FRAMEWORK to generic_structure.
- Source-attributed material (synthesis evidence, outline material_map) never
  reached the writer prompt.
- The writer prompt contained instructions that actively invited fabrication.

No network access: every test works on pure prompt-assembly / yaml loading.
"""
import pytest

from article_pipeline import llm
from article_pipeline.contracts import SynthesisOutput
from article_pipeline.framework import (
    FALLBACK_GENRE,
    build_framework_output,
    find_framework_by_name,
    load_framework_yaml,
    load_manifest,
    resolve_genre,
    run_framework,
)
from article_pipeline.outline import (
    _checked,
    _format_evidence,
    _format_framework_structure,
)
from article_pipeline.prosody import run_prosody_for_category
from article_pipeline.writer import (
    _ANTI_FABRICATION,
    _NEGATIVE_CONSTRAINTS,
    _build_writer_prompt,
    _call_messages_api,
    _genre_rules,
    _load_prosody,
    _render_negative_constraints,
    _render_prosody_block,
    _render_sourced_material,
)


def _synthesis(**kw) -> SynthesisOutput:
    base = dict(
        core_judgment="缓存绕过规则写错会让命中率归零",
        evidence_for=[{"source": "Nginx 官方文档",
                       "claim": "fastcgi_cache_bypass 命中即跳过缓存",
                       "strength": 0.9}],
        evidence_against=[{"source": "社区帖", "claim": "很多人以为装上插件就有缓存"}],
        conflicts=[],
        unique_claims=["实测 bypass 规则写错把命中率打到 0"],
        differentiation="含实测 bypass 配置对比，搜索结果只有理论描述",
        confidence=0.8,
    )
    base.update(kw)
    return SynthesisOutput(**base)


def _outline(**kw) -> dict:
    base = {
        "titles": [{"style": "seo", "text": "测试标题"}],
        "core_argument": "核心论点",
        "sections": [{"heading": "问题场景", "points": ["要点1"]}],
    }
    base.update(kw)
    return base


# ── Genre resolution ──

@pytest.mark.parametrize("label,expected", [
    ("tutorial", "tutorial"),
    ("case_study", "case-study"),      # pipeline's _map_category_to_genre output
    ("case-study", "case-study"),
    ("tool_review", "tool-review"),
    ("TUTORIAL", "tutorial"),
    (" opinion ", "opinion"),
])
def test_resolve_genre_normalises_separators(label, expected):
    assert resolve_genre(label) == expected


def test_resolve_genre_unknown_falls_back():
    assert resolve_genre("no-such-genre") == FALLBACK_GENRE
    assert resolve_genre("") == FALLBACK_GENRE
    assert resolve_genre(None) == FALLBACK_GENRE


@pytest.mark.parametrize("label", ["case_study", "tool_review", "no-such-genre"])
def test_prosody_does_not_raise_on_underscore_or_unknown_genre(label):
    """Regression: these raised ValueError and aborted the prosody stage."""
    prosody = run_prosody_for_category(label)
    assert prosody is not None
    assert prosody.samples, "prosody must still load real samples after fallback"
    assert prosody.rhythm_hint
    assert prosody.negative_constraints


def test_prosody_underscore_genre_gets_same_output_as_hyphen():
    assert (run_prosody_for_category("case_study").sample_type
            == run_prosody_for_category("case-study").sample_type)


# ── FRAMEWORK: stop discarding authored yaml content ──

def test_framework_preserves_h2_titles_from_yaml():
    """Regression: h2_title was overwritten with "" and never refilled."""
    data = load_framework_yaml("tutorial")
    fw = build_framework_output(data, _synthesis(), "tutorial")
    titles = [s["h2_title"] for s in fw.structure]
    assert all(titles), f"h2_title discarded: {titles}"
    assert "问题场景" in titles


def test_framework_preserves_pattern_from_yaml():
    fw = build_framework_output(load_framework_yaml("tutorial"), _synthesis(), "tutorial")
    assert all(s["pattern"] for s in fw.structure)


def test_framework_note_carries_principles_and_anti_patterns():
    """principles / anti_patterns existed in every yaml and reached no prompt."""
    fw = build_framework_output(load_framework_yaml("tutorial"), _synthesis(), "tutorial")
    assert "方法论原则" in fw.freeform_note
    assert "反模式" in fw.freeform_note
    assert "不要用概念定义开头" in fw.freeform_note


def test_framework_underscore_genre_keeps_its_methodology():
    """Regression: "case_study" silently degraded to generic_structure."""
    assert run_framework(_synthesis(), "case_study").method == "narrative_arc"
    assert run_framework(_synthesis(), "case-study").method == "narrative_arc"


def test_framework_unknown_genre_still_produces_usable_structure():
    fw = run_framework(_synthesis(), "no-such-genre")
    assert fw.structure
    assert fw.takeaway == _synthesis().core_judgment


def test_framework_entry_state_is_not_filler():
    """Old code emitted "读者对 <genre> 话题有基本了解" — pure filler."""
    fw = run_framework(_synthesis(), "tutorial")
    assert "话题有基本了解" not in fw.reader_entry_state
    assert fw.reader_entry_state


def test_manifest_fallback_names_are_resolvable_or_absent():
    """preferred/fallback were read then dropped; now they must resolve or log."""
    assert find_framework_by_name("cognitive_scaffold") is not None
    assert find_framework_by_name("definitely_not_a_framework") is None


def test_run_framework_uses_manifest_when_genre_yaml_missing(tmp_path, monkeypatch):
    import article_pipeline.framework as fwmod
    genres = tmp_path / "genres"
    (genres / "orphan").mkdir(parents=True)
    (genres / "orphan" / "manifest.yaml").write_text(
        "preferred_framework: borrowed_method\nfallback_framework: generic_structure\n",
        encoding="utf-8")
    (genres / "lender").mkdir(parents=True)
    (genres / "lender" / "framework.yaml").write_text(
        "name: borrowed_method\nstructure:\n"
        "  - role: opening\n    purpose: 开场\n    h2_title: 开场\n",
        encoding="utf-8")
    monkeypatch.setattr(fwmod, "GENRES_DIR", genres)
    monkeypatch.setattr(fwmod, "FALLBACK_GENRE", "orphan")

    fw = fwmod.run_framework(_synthesis(), "orphan")
    assert fw.method == "borrowed_method", "manifest.preferred_framework still ignored"


# ── OUTLINE: framework fields reach the prompt; gate no longer raises ──

def test_outline_renders_h2_title_and_pattern():
    fw = build_framework_output(load_framework_yaml("tutorial"), _synthesis(), "tutorial")
    text = _format_framework_structure(fw.structure)
    assert "H2 标题建议: 问题场景" in text
    assert "展开方式:" in text


def test_outline_evidence_is_numbered_and_sourced():
    text = _format_evidence(_synthesis().evidence_for)
    assert "[E1]" in text
    assert "（来源: Nginx 官方文档）" in text


def test_differentiation_gate_returns_error_instead_of_raising():
    """Raising escaped the stage's retry logic and marked the task skipped."""
    bad = _checked({"differentiation": "深入分析"})
    assert bad["error"] == "differentiation_rejected"
    assert "message" in bad


def test_differentiation_gate_passes_good_input():
    good = {"differentiation": "包含 elementary 实测的性能数据，搜索结果都是理论描述"}
    assert _checked(good) is good


# ── WRITER: PROSODY is actually consumed ──

def test_writer_prompt_contains_prosody_samples_and_rhythm():
    prosody = _load_prosody("tutorial")
    assert prosody is not None and prosody.samples
    prompt = _build_writer_prompt("Nginx 缓存", "tutorial", _outline(), "素材" * 200)
    assert "语感范本" in prompt
    assert prosody.rhythm_hint in prompt
    assert prosody.samples[0][:40] in prompt


def test_writer_prompt_warns_against_copying_sample_facts():
    prompt = _build_writer_prompt("k", "tutorial", _outline(), "素材" * 200)
    assert "范本里的事实、数字、公司名一律不得搬进文章" in prompt


def test_writer_uses_prosody_negative_constraints():
    """Regression: prosody.negative_constraints was stored in the DB, never used."""
    block = _render_negative_constraints("tutorial")
    assert "你只需要" in block, "tutorial-specific prosody bans missing"
    assert _NEGATIVE_CONSTRAINTS in block, "writer's structural bans must survive"


def test_negative_constraints_are_genre_aware():
    assert "我个人认为" in _render_negative_constraints("opinion")
    assert "我个人认为" not in _render_negative_constraints("tutorial")


class _FakeProsody:
    def __init__(self, negative_constraints):
        self.negative_constraints = negative_constraints
        self.samples = []
        self.rhythm_hint = ""


def test_negative_constraints_drop_fully_redundant_prosody_lines():
    """A prosody line whose every banned phrase is already in the writer block
    must not be paid for twice."""
    fake = _FakeProsody(
        "- 不使用「值得注意的是」——虚指引入\n"      # already banned above
        "- 不使用「换句话说」「独有短语ABC」的表达\n"  # partially new -> keep
        "- 不使用「另一个独有短语」\n"                # fully new -> keep
    )
    merged = _render_negative_constraints("tutorial", fake)
    assert merged.count("值得注意的是") == _NEGATIVE_CONSTRAINTS.count("值得注意的是")
    assert "独有短语ABC" in merged
    assert "另一个独有短语" in merged


def test_writer_prompt_degrades_without_prosody():
    """Missing samples must not break writing."""
    block = _render_prosody_block(None, [{"claim": "补充观点"}])
    assert "补充观点" in block
    assert _render_prosody_block(None, None) == ""
    assert _render_negative_constraints("tutorial", object()) == _NEGATIVE_CONSTRAINTS


# ── WRITER: source-attributed material ──

def test_sourced_evidence_reaches_writer_prompt():
    ev = _synthesis().evidence_for
    prompt = _build_writer_prompt("k", "tutorial", _outline(), "素材" * 200, evidence=ev)
    assert "可引用素材" in prompt
    assert "fastcgi_cache_bypass 命中即跳过缓存" in prompt
    assert "（来源: Nginx 官方文档）" in prompt


def test_unsourced_evidence_is_marked_unquotable():
    block = _render_sourced_material([{"claim": "某个说法"}], None)
    assert "不可引用" in block


def test_material_map_reaches_writer_prompt():
    """outline asks for material_map; _build_writer_prompt never read the key."""
    outline = _outline(material_map=[
        {"section_index": 0, "evidence_id": "E1",
         "source": "Nginx 官方文档", "usage": "解释 cache key 设计"},
    ])
    prompt = _build_writer_prompt("k", "tutorial", outline, "素材" * 200)
    assert "素材分配" in prompt
    assert "解释 cache key 设计" in prompt


def test_sourced_material_block_empty_when_nothing_available():
    assert _render_sourced_material(None, None) == ""
    assert _render_sourced_material([], []) == ""


# ── WRITER: anti-fabrication discipline ──

def test_anti_fabrication_block_present_in_every_tier():
    for tier in ("TIER_INTERNAL", "TIER_EXTERNAL"):
        prompt = _build_writer_prompt("k", "tutorial", _outline(), "素材" * 200, tier=tier)
        assert "反编造纪律" in prompt


@pytest.mark.parametrize("rule", [
    "可溯源原则", "标注来源", "禁止社会证明造假",
    "API 与常量禁止臆测", "代码必须可运行且自洽", "缺口是合法输出",
])
def test_anti_fabrication_covers_observed_failure_modes(rule):
    assert rule in _ANTI_FABRICATION


def test_anti_fabrication_outranks_other_requirements():
    assert "优先级高于所有其他要求" in _ANTI_FABRICATION


def test_marketing_rules_no_longer_ask_for_invented_testimonials():
    """Old rule: 用具体数字建立信任（"已有2300+开发者使用"），没有数据用用户证言."""
    rules = _genre_rules("marketing", "TIER_EXTERNAL")
    assert "2300+" not in rules
    assert "没有数据用用户证言" not in rules
    assert "不要编数字" in rules


@pytest.mark.parametrize("category,banned", [
    ("case-study", "日活3000"),
    ("case-study", "3s→0.8s"),
    ("comparison", "TTFB差距约200ms"),
    ("trend", "React份额从38%降到33%"),
])
def test_genre_rules_do_not_seed_fabricated_example_numbers(category, banned):
    """Invented exemplar numbers get copied verbatim into articles."""
    assert banned not in _genre_rules(category)


@pytest.mark.parametrize("category", ["trend", "thought-leadership"])
def test_source_quotas_are_conditional_on_supply(category):
    """"至少两个独立源" with no supply is a fabrication order."""
    rules = _genre_rules(category)
    assert "至少引用两个独立数据源" not in rules
    assert "至少需要两个独立源" not in rules
    assert "不要" in rules and "虚构" in rules


def test_opinion_rules_do_not_contradict_the_ban_list():
    """"X不是Y，而是Z" was demanded by opinion rules and banned two blocks later."""
    rules = _genre_rules("opinion")
    # The ban list forbids the pattern...
    assert "不是 X，而是 Y" in _NEGATIVE_CONSTRAINTS
    # ...so the genre rules must not demand it.
    assert '至少用一个对比来制造张力："X不是Y，而是Z"或' not in rules
    assert "已被硬性禁止" in rules


def test_per_h2_number_quota_yields_to_no_fabrication():
    rules = _genre_rules("tutorial")
    assert "不编造 > 有具体例子" in rules


def test_skip_instruction_does_not_read_as_permission_to_invent():
    from article_pipeline.writer import WRITER_SYSTEM_PROMPT
    assert "不是编一个数字来填" in WRITER_SYSTEM_PROMPT


# ── Model calling strategy ──

def test_resolve_endpoints_omits_unconfigured_writing_model():
    """Default was claude-sonnet-4 sent to whatever base_url was set: a
    guaranteed 4xx round trip on every single call."""
    endpoints = llm.resolve_endpoints({
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-v4-pro",
        "fallback_url": "https://api.z.ai/api/anthropic",
        "fallback_model": "glm-5.1",
    })
    assert all("claude" not in model for _, model in endpoints)
    assert endpoints[0] == ("https://api.deepseek.com/anthropic", "deepseek-v4-pro")
    assert len(endpoints) == 2


def test_resolve_endpoints_honours_explicit_writing_model():
    endpoints = llm.resolve_endpoints({
        "base_url": "https://api.z.ai/api/anthropic",
        "writing_model": "claude-sonnet-4-6",
        "writing_url": "https://api.anthropic.com",
        "model": "glm-5.1",
    })
    assert endpoints[0] == ("https://api.anthropic.com", "claude-sonnet-4-6")
    assert len(endpoints) == 3


def test_resolve_endpoints_drops_incomplete_pairs():
    assert llm.resolve_endpoints({"base_url": "", "model": "", "fallback_url": "",
                                  "fallback_model": ""}) == []


def test_writer_api_adapter_renames_content_to_article(monkeypatch):
    import article_pipeline.writer as w
    monkeypatch.setattr(w, "llm_call_messages_api",
                        lambda *a, **k: {"content": "正文", "model": "m", "tokens": {"x": 1}})
    assert _call_messages_api("u", "k", "m", "s", "p")["article"] == "正文"


def test_writer_api_adapter_passes_errors_through(monkeypatch):
    import article_pipeline.writer as w
    monkeypatch.setattr(w, "llm_call_messages_api",
                        lambda *a, **k: {"error": "client_error", "message": "HTTP 404"})
    assert _call_messages_api("u", "k", "m", "s", "p")["error"] == "client_error"


def test_call_with_fallback_reports_missing_key_without_network(monkeypatch):
    import article_pipeline.writer as w
    monkeypatch.setattr(w, "_get_api_key", lambda: None)
    assert w._call_with_fallback("s", "p")["error"] == "missing_api_key"


# ── SYNTHESIS: the cascade root must know the topic ──

def test_run_synthesis_forwards_keyword(monkeypatch):
    """_call_synthesis_llm always accepted keyword; run_synthesis never passed it."""
    import article_pipeline.synthesis as sm
    seen = {}

    def fake(sources, keyword=""):
        seen["keyword"] = keyword
        return {"core_judgment": "j", "confidence": 0.9}

    monkeypatch.setattr(sm, "_call_synthesis_llm", fake)
    sm.run_synthesis({}, keyword="Nginx 缓存")
    assert seen["keyword"] == "Nginx 缓存"


def test_synthesis_keyword_reaches_the_prompt(monkeypatch):
    import article_pipeline.synthesis as sm
    captured = {}

    def fake_call(system_prompt, user_prompt, max_tokens=0, temperature=None):
        captured["user"] = user_prompt
        captured["temperature"] = temperature
        return {"content": '{"core_judgment":"j","confidence":0.9}'}

    monkeypatch.setattr(sm, "call_with_fallback", fake_call)
    sm.run_synthesis({"annotations": [{"book": "B", "claim": "C"}]}, keyword="Nginx 缓存")
    assert "Nginx 缓存" in captured["user"]
    assert captured["temperature"] == 0.3, "synthesis must stay cold"


def test_synthesis_prompt_demands_named_sources():
    from article_pipeline.synthesis import SYNTHESIS_PROMPT
    assert "禁止写" in SYNTHESIS_PROMPT and "业内共识" in SYNTHESIS_PROMPT
    assert "必须能在素材里逐字找到" in SYNTHESIS_PROMPT


def test_synthesis_preserves_freeform_note(monkeypatch):
    """contracts declared freeform_note, the prompt never asked for it and
    run_synthesis never read it — framework/outline consume that channel."""
    import article_pipeline.synthesis as sm
    monkeypatch.setattr(sm, "_call_synthesis_llm",
                        lambda s, keyword="": {"core_judgment": "j", "confidence": 0.9,
                                               "freeform_note": "素材可信度偏低"})
    assert sm.run_synthesis({}).freeform_note == "素材可信度偏低"


def test_framework_note_carries_synthesis_freeform_note():
    fw = build_framework_output(load_framework_yaml("tutorial"),
                               _synthesis(freeform_note="来源不明的观察"), "tutorial")
    assert "来源不明的观察" in fw.freeform_note
