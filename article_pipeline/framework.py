"""Framework layer — methodology-based outline generation.

This layer loads genre-specific framework.yaml and builds a methodology-driven
outline structure, replacing template-based outline generation.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

from article_pipeline.contracts import SynthesisOutput


# Path to genre definitions
GENRES_DIR = Path(__file__).parent.parent / "article_pipeline" / "genres"


@dataclass
class FrameworkOutput:
    """Layer 2 -> Layer 5 contract.

    Framework layer output defining article structure and methodology.
    """
    method: str  # Methodology name (e.g. "cognitive_scaffold")
    structure: list[dict]  # [{role, h2_title, purpose, evidence_ids, word_budget}]
    takeaway: str  # One-line value proposition
    reader_entry_state: str  # What reader believes coming in
    reader_exit_state: str  # What reader should understand going out
    visual_anchors: list[dict] | None = None  # Optional visual references
    freeform_note: str = ""  # Nuanced info that doesn't fit fields


def load_framework_yaml(genre: str) -> dict:
    """Load framework.yaml for a genre.

    Args:
        genre: Genre identifier (e.g. "tutorial", "comparison")

    Returns:
        Parsed framework.yaml content

    Raises:
        FileNotFoundError: If framework.yaml doesn't exist
    """
    genre_path = GENRES_DIR / genre / "framework.yaml"

    if not genre_path.exists():
        # Fallback to generic framework
        return {
            "name": "generic_structure",
            "display_name": "通用结构",
            "description": "基础文章结构",
            "structure": [
                {"role": "opening", "purpose": "引入话题", "word_budget": "100-200"},
                {"role": "body", "purpose": "展开论述", "word_budget": "800-1500"},
                {"role": "conclusion", "purpose": "总结要点", "word_budget": "100-150"},
            ]
        }

    with open(genre_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_manifest(genre: str) -> dict:
    """Load manifest.yaml for a genre."""
    manifest_path = GENRES_DIR / genre / "manifest.yaml"

    if not manifest_path.exists():
        return {
            "preferred_framework": "generic_structure",
            "fallback_framework": "generic_structure",
        }

    with open(manifest_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


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
            "h2_title": "",  # To be filled by outline generation
            "evidence_ids": [],
        }
        structure.append(section)

    # Build takeaway from synthesis
    takeaway = synthesis.core_judgment if synthesis.core_judgment else ""

    # Reader state (generic defaults, could be enhanced)
    reader_entry_state = f"读者对 {genre} 话题有基本了解"
    reader_exit_state = f"读者理解了{takeaway}"

    return FrameworkOutput(
        method=method,
        structure=structure,
        takeaway=takeaway,
        reader_entry_state=reader_entry_state,
        reader_exit_state=reader_exit_state,
        visual_anchors=None,
        freeform_note=synthesis.freeform_note,
    )


def run_framework(synthesis: SynthesisOutput, genre: str) -> FrameworkOutput:
    """Run framework layer: load methodology and build structure.

    Args:
        synthesis: SynthesisOutput from Layer 1
        genre: Genre identifier

    Returns:
        FrameworkOutput with methodology-driven structure
    """
    # Load genre manifest to get preferred framework
    manifest = load_manifest(genre)
    preferred = manifest.get("preferred_framework", "generic_structure")
    fallback = manifest.get("fallback_framework", "generic_structure")

    # Try to load preferred framework
    framework_path = GENRES_DIR / genre / "framework.yaml"
    if framework_path.exists():
        with open(framework_path, 'r', encoding='utf-8') as f:
            framework_data = yaml.safe_load(f)
    else:
        # Use generic framework
        framework_data = {
            "name": "generic_structure",
            "display_name": "通用结构",
            "structure": [
                {"role": "opening", "purpose": "引入话题", "word_budget": "100-200"},
                {"role": "body", "purpose": "展开论述", "word_budget": "800-1500"},
                {"role": "conclusion", "purpose": "总结要点", "word_budget": "100-150"},
            ]
        }

    # Build framework output
    return build_framework_output(framework_data, synthesis, genre)


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
