"""Framework layer — methodology-based outline generation.

This layer loads genre-specific framework.yaml and builds a methodology-driven
outline structure, replacing template-based outline generation.
"""

import logging
import yaml
from pathlib import Path

from article_pipeline.contracts import FrameworkOutput, SynthesisOutput

logger = logging.getLogger(__name__)


# Path to genre definitions
GENRES_DIR = Path(__file__).parent / "genres"

# Genre directory used when a category maps to no directory at all.
FALLBACK_GENRE = "guide"


def resolve_genre(genre: str) -> str:
    """Map a pipeline category / genre label onto an existing genres/ directory.

    The pipeline's category vocabulary uses hyphens ("case-study") while some
    call sites use underscores ("case_study"). Both must resolve, otherwise the
    framework silently degrades to generic_structure and prosody raises.

    Returns the resolved directory name, or FALLBACK_GENRE when nothing matches.
    """
    raw = (genre or "").strip().lower()
    if not raw:
        return FALLBACK_GENRE

    candidates = [raw, raw.replace("_", "-"), raw.replace("-", "_")]
    seen = []
    for cand in candidates:
        if cand in seen:
            continue
        seen.append(cand)
        if (GENRES_DIR / cand).is_dir():
            return cand

    logger.warning("genre %r has no genres/ directory, falling back to %r",
                   genre, FALLBACK_GENRE)
    return FALLBACK_GENRE


def _generic_framework() -> dict:
    """Last-resort framework used when no genre or named framework resolves."""
    return {
        "name": "generic_structure",
        "display_name": "通用结构",
        "description": "基础文章结构",
        "structure": [
            {"role": "opening", "purpose": "引入话题", "word_budget": "100-200"},
            {"role": "body", "purpose": "展开论述", "word_budget": "800-1500"},
            {"role": "conclusion", "purpose": "总结要点", "word_budget": "100-150"},
        ],
    }


def load_framework_yaml(genre: str) -> dict:
    """Load framework.yaml for a genre.

    Args:
        genre: Genre identifier (e.g. "tutorial", "comparison")

    Returns:
        Parsed framework.yaml content, or the generic framework when the genre
        has no framework.yaml.
    """
    genre_path = GENRES_DIR / resolve_genre(genre) / "framework.yaml"

    if not genre_path.exists():
        return _generic_framework()

    with open(genre_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else _generic_framework()


def load_manifest(genre: str) -> dict:
    """Load manifest.yaml for a genre."""
    manifest_path = GENRES_DIR / resolve_genre(genre) / "manifest.yaml"

    if not manifest_path.exists():
        return {
            "preferred_framework": "generic_structure",
            "fallback_framework": "generic_structure",
        }

    with open(manifest_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def find_framework_by_name(name: str) -> dict | None:
    """Search every genre directory for a framework.yaml declaring ``name``.

    This is what makes manifest.preferred_framework / fallback_framework real:
    a genre without its own framework.yaml can borrow a methodology declared
    elsewhere instead of silently collapsing to generic_structure.
    """
    if not name:
        return None
    for framework_path in sorted(GENRES_DIR.glob("*/framework.yaml")):
        try:
            with open(framework_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("name") == name:
            return data
    return None


def _render_methodology_note(framework_data: dict, synthesis: SynthesisOutput) -> str:
    """Collapse the framework.yaml prose fields into the freeform_note channel.

    ``principles``, ``anti_patterns`` and ``quality_gates`` are authored in every
    genres/*/framework.yaml but had no field in FrameworkOutput, so they never
    reached any prompt. freeform_note is the contract's designated overflow slot
    and outline.py renders it as the methodology description, so route them here.
    """
    parts = []

    description = (framework_data.get("description") or "").strip()
    display_name = (framework_data.get("display_name") or "").strip()
    if display_name:
        parts.append(f"方法论：{display_name}")
    if description:
        parts.append(description)

    for key, label in (("principles", "方法论原则"),
                       ("anti_patterns", "反模式（必须避免）"),
                       ("quality_gates", "质量门槛（成稿必须满足）")):
        items = framework_data.get(key) or []
        items = [str(i).strip() for i in items if str(i).strip()]
        if items:
            parts.append(f"{label}:\n" + "\n".join(f"- {i}" for i in items))

    note = (synthesis.freeform_note or "").strip()
    if note:
        parts.append(f"素材层补充：{note}")

    return "\n\n".join(parts)


def build_framework_output(
    framework_data: dict,
    synthesis: SynthesisOutput,
    genre: str
) -> FrameworkOutput:
    """Build FrameworkOutput from framework.yaml and synthesis.

    Args:
        framework_data: Parsed framework.yaml content
        synthesis: SynthesisOutput from Layer 1
        genre: Genre identifier

    Returns:
        FrameworkOutput with methodology-driven structure
    """
    method = framework_data.get("name", "generic_structure")

    # Build structure from framework template
    structure = []
    framework_structure = framework_data.get("structure", [])

    for item in framework_structure:
        section = {
            "role": item.get("role", "body"),
            "purpose": item.get("purpose", ""),
            "word_budget": item.get("word_budget", "200-400"),
            "pattern": item.get("pattern", ""),
            # h2_title is authored in framework.yaml; keep it as the suggested
            # heading instead of blanking it (outline.py renders this field).
            "h2_title": item.get("h2_title", ""),
            "evidence_ids": [],
        }
        structure.append(section)

    # Build takeaway from synthesis
    takeaway = synthesis.core_judgment if synthesis.core_judgment else ""

    # Reader states: prefer what the genre declares, fall back to synthesis.
    reader_entry_state = (framework_data.get("reader_entry_state") or "").strip()
    if not reader_entry_state:
        misunderstanding = ""
        for item in synthesis.evidence_against or []:
            if isinstance(item, dict):
                misunderstanding = (item.get("claim") or item.get("text") or "").strip()
                if misunderstanding:
                    break
        reader_entry_state = misunderstanding or f"读者对「{genre}」话题只有零散印象，尚未形成判断"

    reader_exit_state = (framework_data.get("reader_exit_state") or "").strip()
    if not reader_exit_state:
        reader_exit_state = f"读者理解了{takeaway}" if takeaway else "读者带走一个可执行的判断"

    return FrameworkOutput(
        method=method,
        structure=structure,
        takeaway=takeaway,
        reader_entry_state=reader_entry_state,
        reader_exit_state=reader_exit_state,
        visual_anchors=None,
        freeform_note=_render_methodology_note(framework_data, synthesis),
    )


def run_framework(synthesis: SynthesisOutput, genre: str) -> FrameworkOutput:
    """Run framework layer: load methodology and build structure.

    Args:
        synthesis: SynthesisOutput from Layer 1
        genre: Genre identifier

    Returns:
        FrameworkOutput with methodology-driven structure
    """
    resolved = resolve_genre(genre)

    # Load genre manifest to get preferred / fallback framework names
    manifest = load_manifest(resolved)
    preferred = manifest.get("preferred_framework") or "generic_structure"
    fallback = manifest.get("fallback_framework") or "generic_structure"

    framework_data = None

    # 1. The genre's own framework.yaml is authoritative when present.
    framework_path = GENRES_DIR / resolved / "framework.yaml"
    if framework_path.exists():
        with open(framework_path, 'r', encoding='utf-8') as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict) and loaded.get("structure"):
            framework_data = loaded
            if loaded.get("name") != preferred:
                # Config drift: surface it instead of pretending the manifest ran.
                logger.warning(
                    "genre %r: manifest declares preferred_framework=%r but "
                    "framework.yaml declares name=%r — using framework.yaml",
                    resolved, preferred, loaded.get("name"))

    # 2. No usable framework.yaml → honour the manifest's declared names.
    if framework_data is None:
        for name in (preferred, fallback):
            found = find_framework_by_name(name)
            if found and found.get("structure"):
                logger.info("genre %r: borrowing framework %r", resolved, name)
                framework_data = found
                break

    # 3. Nothing resolved → generic structure.
    if framework_data is None:
        logger.warning("genre %r: no framework resolved (preferred=%r fallback=%r), "
                       "using generic_structure", resolved, preferred, fallback)
        framework_data = _generic_framework()

    # Build framework output
    return build_framework_output(framework_data, synthesis, resolved)


if __name__ == "__main__":
    # Test framework layer
    from article_pipeline.contracts import SynthesisOutput

    test_synthesis = SynthesisOutput(
        core_judgment="Nginx 缓存可显著降低后端压力",
        evidence_for=[],
        evidence_against=[],
        conflicts=[],
        unique_claims=[],
        differentiation="基于实测数据，非理论描述",
        confidence=0.8,
    )

    framework = run_framework(test_synthesis, "tutorial")
    print("=== Framework Output ===")
    print(f"Method: {framework.method}")
    print(f"Takeaway: {framework.takeaway}")
    print(f"Structure sections: {len(framework.structure)}")
    for section in framework.structure:
        print(f"  - {section['role']}: {section['purpose']}")
